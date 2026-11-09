"""Host-side tests for bodyrig.vrm_export (no Blender needed).

The Blender run is replaced by a fake ``run_bounded`` that writes what the
real worker would; tests/test_vrm_export_blender.py covers real Blender.
"""

from __future__ import annotations

import json
import os
import stat
import zipfile
from pathlib import Path

import pytest

from bodyrig import humanoid_names as hn
from bodyrig import vrm_export as ve
from bodyrig.process_limits import BoundedResult
from bodyrig.scene_inspector import BlenderRuntime


# --- humanoid names -----------------------------------------------------------------------

@pytest.mark.parametrize("name, expected", [
    ("root hips", "hips"), ("spine lower", "spine"), ("spine middle", "chest"), ("head neck lower", "neck"),
    ("arm left shoulder 1", "left_shoulder"), ("arm left shoulder 2", "left_upper_arm"),
    ("arm right elbow", "right_lower_arm"), ("arm right wrist", "right_hand"),
    ("leg left thigh", "left_upper_leg"), ("leg right knee", "right_lower_leg"), ("leg left ankle", "left_foot"),
    ("ValveBiped.Bip01_Pelvis", "hips"), ("ValveBiped.Bip01_Spine", "spine"), ("ValveBiped.Bip01_Spine1", "chest"),
    ("ValveBiped.Bip01_Neck1", "neck"), ("ValveBiped.Bip01_Head1", "head"),
    ("ValveBiped.Bip01_L_UpperArm", "left_upper_arm"), ("ValveBiped.Bip01_R_Forearm", "right_lower_arm"),
    ("ValveBiped.Bip01_L_Thigh", "left_upper_leg"), ("ValveBiped.Bip01_R_Calf", "right_lower_leg"),
    ("hip", "hips"), ("abdomenLower", "spine"), ("chestUpper", "chest"), ("lShldrBend", "left_upper_arm"),
    ("rForearmBend", "right_lower_arm"), ("lThighBend", "left_upper_leg"), ("rShin", "right_lower_leg"),
    ("mixamorig:Hips", "hips"), ("mixamorig:LeftArm", "left_upper_arm"), ("mixamorig:RightUpLeg", "right_upper_leg"),
    ("mixamorig:LeftLeg", "left_lower_leg"), ("upper_arm.L", "left_upper_arm"), ("UpperArm_R", "right_upper_arm"),
])
def test_role_of_known_families(name, expected):
    assert hn.role_of(name) == expected


@pytest.mark.parametrize("name", ["Bone.003", "head eyeball left", "arm", "breast left", "hair 1", ""])
def test_role_of_unknown_or_sideless(name):
    assert hn.role_of(name) is None


def test_map_bones_first_wins_and_reports_missing():
    names = ["hip", "pelvis", "abdomenLower", "head", "lThighBend"]
    mapping = hn.map_bones(names)
    assert mapping["hips"] == "hip"  # Daz pelvis is a child of hip; the first one wins
    missing = hn.missing_required(mapping)
    assert "left_lower_leg" in missing and "hips" not in missing


# --- naming, staging, zip safety ----------------------------------------------------------

@pytest.mark.parametrize("given, expected", [
    ("Model Pack (v2).zip", "Model_Pack_v2"), ("figure.mesh.ascii", "figure"), ("hero.FBX", "hero"),
    ("../evil.zip", "evil"), ("....zip", "model"),
])
def test_output_name(given, expected):
    assert ve.output_name(Path(given)) == expected


def _zip(path: Path, entries: dict[str, bytes], links: tuple[str, ...] = ()) -> Path:
    with zipfile.ZipFile(path, "w") as bundle:
        for name, data in entries.items():
            bundle.writestr(name, data)
        for name in links:
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            bundle.writestr(info, "/etc/passwd")
    return path


@pytest.mark.parametrize("bad", ["../escape.txt", "/abs.txt", "C:/win.txt", "a/../../b.txt"])
def test_extract_zip_rejects_escaping_paths(tmp_path, bad):
    archive = _zip(tmp_path / "a.zip", {"ok.fbx": b"x", bad: b"y"})
    with pytest.raises(ve.VrmExportError) as err:
        ve.extract_zip(archive, tmp_path / "out", max_bytes=1 << 20, max_entries=100)
    assert err.value.code == "unsafe_path"
    assert not (tmp_path / "escape.txt").exists()


def test_extract_zip_rejects_links(tmp_path):
    archive = _zip(tmp_path / "a.zip", {"ok.fbx": b"x"}, links=("tex/skin.png",))
    with pytest.raises(ve.VrmExportError) as err:
        ve.extract_zip(archive, tmp_path / "out", max_bytes=1 << 20, max_entries=100)
    assert err.value.code == "unsafe_path"


def test_extract_zip_size_and_count_limits(tmp_path):
    archive = _zip(tmp_path / "a.zip", {f"f{i}.png": b"0" * 1000 for i in range(5)})
    with pytest.raises(ve.VrmExportError) as err:
        ve.extract_zip(archive, tmp_path / "o1", max_bytes=2500, max_entries=100)
    assert err.value.code == "asset_too_large"
    with pytest.raises(ve.VrmExportError) as err:
        ve.extract_zip(archive, tmp_path / "o2", max_bytes=1 << 20, max_entries=3)
    assert err.value.code == "invalid_asset"
    assert ve.extract_zip(archive, tmp_path / "o3", max_bytes=1 << 20, max_entries=100) == 5000


def test_extract_zip_rejects_non_zip(tmp_path):
    (tmp_path / "x.zip").write_bytes(b"not a zip")
    with pytest.raises(ve.VrmExportError) as err:
        ve.extract_zip(tmp_path / "x.zip", tmp_path / "o", max_bytes=1 << 20, max_entries=10)
    assert err.value.code == "invalid_asset"


def test_choose_model_prefers_xps_then_largest(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "small.mesh").write_bytes(b"1")
    (tmp_path / "a" / "big.mesh").write_bytes(b"12345")
    (tmp_path / "preview.fbx").write_bytes(b"123456789")
    (tmp_path / "readme.txt").write_text("x")
    assert ve.choose_model(tmp_path).name == "big.mesh"
    with pytest.raises(ve.VrmExportError):
        ve.choose_model(tmp_path / "a" / "missing")


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_copy_tree_skips_links(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "model.fbx").write_bytes(b"m")
    (tmp_path / "secret.txt").write_text("s")
    os.symlink(tmp_path / "secret.txt", src / "skin.png")
    dest = tmp_path / "dest"
    ve.copy_tree(src, dest, max_bytes=1 << 20)
    assert (dest / "model.fbx").is_file() and not (dest / "skin.png").exists()


# --- export_asset with a fake Blender -----------------------------------------------------

def _runtime(tmp_path: Path) -> BlenderRuntime:
    return BlenderRuntime("module", Path(os.sys.executable), "4.5.15")


def _addons(tmp_path: Path) -> Path:
    addons = tmp_path / "addons"
    (addons / "io_scene_vrm").mkdir(parents=True)
    (addons / "io_scene_vrm" / "__init__.py").write_text("")
    (addons / ve.ADDON_STAMP).write_text(json.dumps({"pins": {"io_scene_vrm": {"commit": "abc"}}}))
    return addons


def _fake_runner(calls: list, *, ok: bool = True, write_doc: bool = True):
    def fake(argv, *, cwd, env, limits, stdout_path, stderr_path):
        args = argv[argv.index("--") + 1:]
        get = lambda flag: args[args.index(flag) + 1]  # noqa: E731
        calls.append({"argv": argv, "env": dict(env), "staging": Path(get("--staging-root")),
                      "files": sorted(p.name for p in Path(get("--staging-root")).rglob("*") if p.is_file())})
        Path(stdout_path).write_text("")
        Path(stderr_path).write_text("boom" if not ok else "")
        doc = {"contract": ve.WORKER_CONTRACT, "complete": True, "timings_ms": {"total": 5},
               "humanoid": {"method": "names", "mapping": {"hips": "root hips"}, "missing_required": []},
               "materials": {"packed": 1}, "bones": 19}
        if ok:
            Path(get("--output-vrm")).write_bytes(b"glTF-fake-vrm")
        else:
            doc["error"] = {"type": "RuntimeError", "message": "missing required humanoid bones: head"}
        if write_doc:
            Path(get("--output")).write_text(json.dumps(doc))
        return BoundedResult(returncode=0 if ok else 3, timed_out=False, memory_exceeded=False, wall_ms=5,
                             peak_memory_bytes=None)
    return fake


def test_export_ready_then_cache_hit(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(ve, "run_bounded", _fake_runner(calls))
    pack = _zip(tmp_path / "Pack One.zip", {"model/figure.mesh.ascii": b"1", "model/textures/skin.png": b"p"})
    kw = dict(runtime=_runtime(tmp_path), addons_dir=_addons(tmp_path), cache_root=tmp_path / "cache",
              work_root=tmp_path / "work", options=ve.ExportOptions(isolation="none"))
    first = ve.export_asset(pack, tmp_path / "out", **kw)
    assert first["state"] == "READY", first
    assert first["output"] == "Pack_One.vrm" and first["cache"]["hit"] is False
    assert first["likeness_authority"] is False and first["model_file"] == "model/figure.mesh.ascii"
    assert (tmp_path / "out" / "Pack_One.vrm").read_bytes() == b"glTF-fake-vrm"
    assert calls[0]["files"] == ["figure.mesh.ascii", "skin.png"]
    assert calls[0]["env"]["CUDA_VISIBLE_DEVICES"] == "" and "127.0.0.1:9" in calls[0]["env"]["HTTPS_PROXY"]
    assert first["cleanup"]["staging_removed"] and not any((tmp_path / "work").iterdir())
    report = json.loads((tmp_path / "out" / "Pack_One.vrm.json").read_text())
    assert report["state"] == "READY" and report["humanoid"]["method"] == "names"

    (tmp_path / "out" / "Pack_One.vrm").unlink()
    second = ve.export_asset(pack, tmp_path / "out", **kw)
    assert second["state"] == "READY" and second["cache"]["hit"] is True and len(calls) == 1
    assert (tmp_path / "out" / "Pack_One.vrm").read_bytes() == b"glTF-fake-vrm"
    assert second["humanoid"]["mapping"] == {"hips": "root hips"}


def test_cache_key_changes_with_addons_options_and_asset(tmp_path):
    rt = _runtime(tmp_path)
    base = ve.cache_key(rt, ve.ExportOptions(), "a" * 64, {"pins": 1})
    assert base != ve.cache_key(rt, ve.ExportOptions(), "b" * 64, {"pins": 1})
    assert base != ve.cache_key(rt, ve.ExportOptions(), "a" * 64, {"pins": 2})
    assert base != ve.cache_key(rt, ve.ExportOptions(max_texture=1024), "a" * 64, {"pins": 1})
    assert base != ve.cache_key(BlenderRuntime("module", rt.executable, "5.0.0"), ve.ExportOptions(), "a" * 64,
                                {"pins": 1})


def test_tampered_cache_entry_is_ignored(tmp_path, monkeypatch):
    calls: list = []
    monkeypatch.setattr(ve, "run_bounded", _fake_runner(calls))
    model = tmp_path / "hero.fbx"
    model.write_bytes(b"fbx")
    kw = dict(runtime=_runtime(tmp_path), addons_dir=_addons(tmp_path), cache_root=tmp_path / "cache",
              work_root=tmp_path / "work", options=ve.ExportOptions(isolation="none"))
    first = ve.export_asset(model, tmp_path / "out", **kw)
    entry = next((tmp_path / "cache").rglob("model.vrm"))
    entry.write_bytes(b"tampered")
    second = ve.export_asset(model, tmp_path / "out", **kw)
    assert second["cache"]["hit"] is False and len(calls) == 2
    assert first["vrm_sha256"] == second["vrm_sha256"]


def test_worker_error_is_failed_with_report(tmp_path, monkeypatch):
    monkeypatch.setattr(ve, "run_bounded", _fake_runner([], ok=False))
    model = tmp_path / "broken.fbx"
    model.write_bytes(b"x")
    result = ve.export_asset(model, tmp_path / "out", runtime=_runtime(tmp_path), addons_dir=_addons(tmp_path),
                             work_root=tmp_path / "work", options=ve.ExportOptions(isolation="none"))
    assert result["state"] == "FAILED" and result["error"]["code"] == "worker_failed"
    assert "head" in result["error"]["message"]
    assert not (tmp_path / "out" / "broken.vrm").exists()
    assert json.loads((tmp_path / "out" / "broken.vrm.json").read_text())["state"] == "FAILED"


def test_worker_without_output_is_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(ve, "run_bounded", _fake_runner([], ok=False, write_doc=False))
    model = tmp_path / "x.glb"
    model.write_bytes(b"x")
    result = ve.export_asset(model, tmp_path / "out", runtime=_runtime(tmp_path), addons_dir=_addons(tmp_path),
                             work_root=tmp_path / "work", options=ve.ExportOptions(isolation="none"))
    assert result["error"]["code"] == "worker_failed" and "boom" in result["error"]["message"]


def test_unsupported_and_missing_assets(tmp_path):
    kw = dict(runtime=_runtime(tmp_path), addons_dir=_addons(tmp_path), work_root=tmp_path / "work",
              options=ve.ExportOptions(isolation="none"))
    (tmp_path / "notes.zip").write_bytes(b"nope")
    assert ve.export_asset(tmp_path / "notes.zip", tmp_path / "out", **kw)["error"]["code"] == "invalid_asset"
    assert ve.export_asset(tmp_path / "gone.fbx", tmp_path / "out", **kw)["error"]["code"] == "invalid_asset"
    empty = _zip(tmp_path / "empty.zip", {"readme.txt": b"x"})
    assert ve.export_asset(empty, tmp_path / "out", **kw)["error"]["code"] == "no_model"


def test_watch_converts_and_sorts_inbox(tmp_path, monkeypatch):
    monkeypatch.setattr(ve, "run_bounded", _fake_runner([]))
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "good.fbx").write_bytes(b"model")
    (inbox / "bad.zip").write_bytes(b"not a zip")
    (inbox / "ignored.txt").write_text("x")
    logs: list[str] = []
    results = ve.watch(inbox, tmp_path / "out", runtime=_runtime(tmp_path), addons_dir=_addons(tmp_path),
                       options=ve.ExportOptions(isolation="none"), work_root=tmp_path / "work",
                       poll_seconds=0.01, settle_seconds=0.01, max_items=2, log=logs.append)
    assert {r["source"]: r["state"] for r in results} == {"good.fbx": "READY", "bad.zip": "FAILED"}
    assert (inbox / "done" / "good.fbx").is_file() and (inbox / "failed" / "bad.zip").is_file()
    assert (inbox / "ignored.txt").is_file() and (tmp_path / "out" / "good.vrm").is_file()
    assert any(line.startswith("[READY] good.fbx") for line in logs)


def test_options_validation():
    with pytest.raises(Exception):
        ve.ExportOptions(isolation="docker").validate()
    with pytest.raises(Exception):
        ve.ExportOptions(max_texture=-1).validate()


def test_addon_pins_are_full_commits():
    for pin in ve.ADDON_PINS.values():
        assert len(pin["commit"]) == 40 and pin["repo"].startswith("https://github.com/")


def test_worker_files_exist_and_worker_is_standalone():
    for path in ve.WORKER_FILES:
        assert path.is_file()
    text = ve.WORKER_SCRIPT.read_text(encoding="utf-8")
    assert "from bodyrig" not in text and "import bodyrig" not in text
