"""Fail-closed texture relinking for the VRM worker (#1399 review by ChatGPT).

Two layers:
- ``bodyrig.vrm_paths`` (pure) is tested directly;
- the worker's real ``_relink_images`` / ``_pack_and_shrink`` run against a fake
  ``bpy``, so the reload boundary itself is covered, including a folder that is
  swapped for a link between indexing and reload (TOCTOU).
"""

from __future__ import annotations

import importlib
import os
import sys
import types
from pathlib import Path

import pytest

from bodyrig import vrm_paths

needs_symlinks = pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")


def _tree(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "src"
    (root / "textures").mkdir(parents=True)
    (root / "textures" / "skin.png").write_bytes(b"inside")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.png").write_bytes(b"outside")
    return root, outside


def test_contained_basic(tmp_path):
    root, outside = _tree(tmp_path)
    assert vrm_paths.contained(str(root / "textures" / "skin.png"), str(root))
    assert not vrm_paths.contained(str(outside / "secret.png"), str(root))
    assert not vrm_paths.contained(str(root / ".." / "outside" / "secret.png"), str(root))
    assert not vrm_paths.contained(str(root), str(root))  # the root itself is not "inside"
    assert not vrm_paths.contained(str(root / "missing.png"), str(root))


@needs_symlinks
def test_contained_rejects_any_link_on_the_way(tmp_path):
    root, outside = _tree(tmp_path)
    os.symlink(outside, root / "linked_dir")
    os.symlink(outside / "secret.png", root / "linked.png")
    os.symlink(root / "textures", root / "alias")  # resolves inside the root, still refused
    assert not vrm_paths.contained(str(root / "linked_dir" / "secret.png"), str(root))
    assert not vrm_paths.contained(str(root / "linked.png"), str(root))
    assert not vrm_paths.contained(str(root / "alias" / "skin.png"), str(root))


@needs_symlinks
def test_image_index_skips_linked_files_and_folders(tmp_path):
    root, outside = _tree(tmp_path)
    os.symlink(outside, root / "linked_dir")
    os.symlink(outside / "secret.png", root / "secret.png")
    index = vrm_paths.image_index(str(root))
    assert index["skin.png"] == str(root / "textures" / "skin.png")
    assert "secret.png" not in index and "secret" not in index
    assert all(vrm_paths.contained(p, str(root)) for p in index.values())


# --- the worker's reload boundary, with a fake bpy ----------------------------------------

class FakeImage:
    def __init__(self, name: str, filepath: str, *, has_data: bool = True, size=(64, 64)):
        self.name = name
        self.filepath = filepath
        self.source = "FILE"
        self.packed_file = None
        self.has_data = has_data
        self.size = list(size)
        self.reloaded_from: list[str] = []
        self.freed = False

    def reload(self) -> None:
        self.reloaded_from.append(self.filepath)
        self.has_data = True

    def buffers_free(self) -> None:
        self.freed = True
        self.has_data = False

    def pack(self) -> None:
        self.packed_file = object()

    def scale(self, width: int, height: int) -> None:
        self.size = [width, height]


@pytest.fixture()
def worker(monkeypatch):
    """Import bodyrig/blender_vrm_worker.py the way Blender would, with a fake bpy."""
    fake = types.ModuleType("bpy")
    fake.data = types.SimpleNamespace(images=[])
    fake.path = types.SimpleNamespace(abspath=lambda p: p)
    monkeypatch.setitem(sys.modules, "bpy", fake)
    worker_dir = str(Path(__file__).resolve().parents[1] / "bodyrig")
    monkeypatch.syspath_prepend(worker_dir)
    for name in ("blender_vrm_worker", "blender_scene_worker", "humanoid_names", "vrm_paths"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    module = importlib.import_module("blender_vrm_worker")
    yield module, fake
    for name in ("blender_vrm_worker", "blender_scene_worker", "humanoid_names", "vrm_paths"):
        sys.modules.pop(name, None)


def test_relink_from_subfolder(worker, tmp_path):
    module, bpy = worker
    root, _ = _tree(tmp_path)
    missing = FakeImage("skin.png", "C:\\artist\\work\\skin.png", has_data=False)
    bpy.data.images[:] = [missing]
    report = module._relink_images(str(root))
    assert report == {"relinked_images": 1, "rejected_image_paths": 0}
    assert missing.reloaded_from == [str(root / "textures" / "skin.png")]


def test_existing_outside_path_is_dropped_never_reloaded_or_packed(worker, tmp_path):
    module, bpy = worker
    root, outside = _tree(tmp_path)
    leak = FakeImage("secret.png", str(outside / "secret.png"))  # already loaded by an importer
    bpy.data.images[:] = [leak]
    report = module._relink_images(str(root))
    assert report["rejected_image_paths"] == 1 and leak.reloaded_from == []
    assert leak.filepath == "" and leak.freed
    assert module._pack_and_shrink(2048, str(root))["packed"] == 0 and leak.packed_file is None


@needs_symlinks
def test_symlinked_parent_candidate_is_never_reloaded(worker, tmp_path):
    module, bpy = worker
    root, outside = _tree(tmp_path)
    (root / "textures" / "skin.png").unlink()
    os.symlink(outside, root / "textures" / "linked")
    (outside / "skin.png").write_bytes(b"outside skin")
    image = FakeImage("skin.png", "skin.png", has_data=False)
    bpy.data.images[:] = [image]
    report = module._relink_images(str(root))
    assert report["relinked_images"] == 0 and image.reloaded_from == []


@needs_symlinks
def test_folder_swapped_for_a_link_after_indexing_is_not_reloaded(worker, tmp_path, monkeypatch):
    module, bpy = worker
    root, outside = _tree(tmp_path)
    (outside / "skin.png").write_bytes(b"outside skin")
    image = FakeImage("skin.png", "skin.png", has_data=False)
    bpy.data.images[:] = [image]
    real_index = module.vrm_paths.image_index

    def index_then_swap(staging_root: str):
        index = real_index(staging_root)
        (root / "textures" / "skin.png").unlink()
        (root / "textures").rmdir()
        os.symlink(outside, root / "textures")  # same path, now a link to outside
        return index

    monkeypatch.setattr(module.vrm_paths, "image_index", index_then_swap)
    report = module._relink_images(str(root))
    assert report["relinked_images"] == 0 and image.reloaded_from == []


def test_pack_only_from_inside_and_downscale(worker, tmp_path):
    module, bpy = worker
    root, _ = _tree(tmp_path)
    big = FakeImage("skin.png", str(root / "textures" / "skin.png"), size=(4096, 2048))
    bpy.data.images[:] = [big]
    assert module._pack_and_shrink(2048, str(root)) == {"packed": 1, "downscaled": 1}
    assert big.size == [2048, 1024] and big.packed_file is not None
