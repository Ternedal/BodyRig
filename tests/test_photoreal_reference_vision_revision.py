from __future__ import annotations

import hashlib
from pathlib import Path

from bodyrig.photoreal_reference_vision_revision import (
    MESH_ADAPTER_DEPENDENCIES,
    _composite_revision,
    compute_reference_vision_revision,
)


ROOT = Path(__file__).resolve().parents[1]
MESH_ADAPTER = ROOT / "tools" / "photoreal_reference_vision_adapter_mesh.py"


def test_mesh_adapter_revision_binds_explicit_runtime_dependency_set() -> None:
    revision = compute_reference_vision_revision(MESH_ADAPTER)
    raw_adapter_sha = hashlib.sha256(MESH_ADAPTER.read_bytes()).hexdigest()
    assert len(revision) == 64
    assert revision != raw_adapter_sha
    assert set(MESH_ADAPTER_DEPENDENCIES) == {
        "bodyrig/photoreal_equirectangular_deprojection.py",
        "bodyrig/photoreal_mesh_deprojection.py",
        "bodyrig/photoreal_mesh_projection.py",
        "bodyrig/photoreal_model_set.py",
        "bodyrig/photoreal_reference_vision_revision.py",
        "bodyrig/photoreal_wsl_request_bridge.py",
        "bodyrig/wsl_adapter_bridge.py",
        "tools/photoreal_reference_vision_adapter.py",
        "tools/photoreal_reference_vision_adapter_mesh.py",
    }


def test_arbitrary_adapter_preserves_legacy_single_file_sha(tmp_path: Path) -> None:
    adapter = tmp_path / "adapter.py"
    adapter.write_bytes(b"adapter-v1\n")
    assert compute_reference_vision_revision(adapter) == hashlib.sha256(adapter.read_bytes()).hexdigest()


def test_composite_revision_changes_when_any_dependency_bytes_change(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"a1")
    (tmp_path / "b.py").write_bytes(b"b1")
    first = _composite_revision(tmp_path, ["a.py", "b.py"])
    (tmp_path / "b.py").write_bytes(b"b2")
    second = _composite_revision(tmp_path, ["a.py", "b.py"])
    assert first != second


def test_composite_revision_is_order_independent(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_bytes(b"a")
    (tmp_path / "b.py").write_bytes(b"b")
    assert _composite_revision(tmp_path, ["a.py", "b.py"]) == _composite_revision(
        tmp_path, ["b.py", "a.py"]
    )
