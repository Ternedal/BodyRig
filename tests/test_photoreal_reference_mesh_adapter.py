from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_reference_vision_adapter_mesh.py"
SPEC = importlib.util.spec_from_file_location("bodyrig_photoreal_reference_vision_mesh_adapter_test", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


def test_mesh_wrapper_revision_is_executable_adapter_revision() -> None:
    assert adapter.ADAPTER_NAME == "bodyrig-reference-vision-v1"
    assert len(adapter._self_revision()) == 64
    assert adapter.base._self_revision() == adapter._self_revision()


def test_mesh_wrapper_preserves_runtime_preflight_surface() -> None:
    assert adapter.build_model_set is adapter.base.build_model_set
    assert adapter._load_model_manifest is adapter.base._load_model_manifest
    assert adapter._load_runtime is adapter.base._load_runtime
    assert adapter._faces is adapter.base._faces
    assert adapter._pose_predictions is adapter.base._pose_predictions
    assert adapter._frame_sha is adapter.base._frame_sha
    assert adapter._perceptual_hash is adapter.base._perceptual_hash


def test_frame_analyzer_routes_mshp_through_unique_deprojected_viewports(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = SimpleNamespace(embedding_dimension=512)
    raw_image = object()
    authority = {
        "format": "bodyrig-spherical-v2-projection-authority",
        "version": 1,
        "projection_type": "mshp",
        "mesh_projection_geometry_sha256": "c" * 64,
        "deprojection_authority": False,
    }
    request = {
        "performer_id": "42",
        "sources": [
            {
                "source_key": "scene:s1:E:/vr180.mp4",
                "source_sha256": "a" * 64,
                "resolved_path": "/verified/vr180.mp4",
                "kind": "video",
                "projection": "mshp",
                "projection_authority": authority,
                "samples": [{"timestamp_seconds": 1.0, "eye": "left"}],
            }
        ],
    }
    args = SimpleNamespace(
        bodyrig_adapter=adapter.ADAPTER_NAME,
        bodyrig_revision="r1",
        bodyrig_model_set_sha256="b" * 64,
    )
    monkeypatch.setattr(adapter.base, "_read_sample", lambda *_args: (raw_image, True))
    calls = []

    def deproject(_runtime, image, path, projection_authority, *, eye, cache):
        assert image is raw_image
        calls.append((path, projection_authority, eye, cache))
        return [("v00", object()), ("v01", object())]

    def candidate_rows(_runtime, _image, *, base, candidate_prefix=""):
        return [{**base, "candidate_id": f"{candidate_prefix}person-000"}]

    monkeypatch.setattr(adapter, "deproject_mesh_views", deproject)
    monkeypatch.setattr(adapter.base, "_candidate_rows", candidate_rows)
    result = adapter._frame_result(runtime, request, args)

    assert len(calls) == 1
    assert calls[0][0] == "/verified/vr180.mp4"
    assert calls[0][1] is authority
    assert calls[0][2] == "left"
    assert isinstance(calls[0][3], dict)
    assert [row["candidate_id"] for row in result["observations"]] == ["v00-person-000", "v01-person-000"]
    assert all(row["projection"] == "mshp" for row in result["observations"])


def test_frame_analyzer_routes_cbmp_through_unique_deprojected_viewports(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime = SimpleNamespace(embedding_dimension=512)
    raw_image = object()
    authority = {
        "format": "bodyrig-spherical-v2-projection-authority",
        "version": 1,
        "projection_type": "cbmp",
        "cubemap_layout": 0,
        "cubemap_padding_pixels": 2,
        "deprojection_authority": False,
    }
    request = {
        "performer_id": "42",
        "sources": [
            {
                "source_key": "scene:s1:E:/cube.mp4",
                "source_sha256": "a" * 64,
                "resolved_path": "/verified/cube.mp4",
                "kind": "video",
                "projection": "cbmp",
                "projection_authority": authority,
                "samples": [{"timestamp_seconds": 1.0, "eye": "mono"}],
            }
        ],
    }
    args = SimpleNamespace(
        bodyrig_adapter=adapter.ADAPTER_NAME,
        bodyrig_revision="r1",
        bodyrig_model_set_sha256="b" * 64,
    )
    monkeypatch.setattr(adapter.base, "_read_sample", lambda *_args: (raw_image, True))
    calls = []

    def deproject(_runtime, image, projection_authority):
        assert image is raw_image
        calls.append(projection_authority)
        return [("front", object()), ("right", object())]

    def candidate_rows(_runtime, _image, *, base, candidate_prefix=""):
        return [{**base, "candidate_id": f"{candidate_prefix}person-000"}]

    monkeypatch.setattr(adapter, "deproject_cubemap_views", deproject)
    monkeypatch.setattr(adapter.base, "_candidate_rows", candidate_rows)
    result = adapter._frame_result(runtime, request, args)

    assert calls == [authority]
    assert [row["candidate_id"] for row in result["observations"]] == [
        "front-person-000",
        "right-person-000",
    ]
    assert all(row["projection"] == "cbmp" for row in result["observations"])


def test_mesh_wrapper_keeps_spatial_identity_bootstrap_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(adapter.base, "_read_sample", lambda *_args: (object(), True))
    with pytest.raises(adapter.ReferenceVisionError, match="cannot establish identity authority"):
        adapter.base._single_identity(SimpleNamespace(), {}, {})


def test_reference_p0_runner_uses_mesh_wrapper_as_the_executable_adapter() -> None:
    script = (ROOT / "run-photoreal-p0-reference-windows.ps1").read_text(encoding="utf-8")
    assert 'tools\\photoreal_reference_vision_adapter_mesh.py' in script
    assert '$adapter = Need-File' in script
    assert '--adapter-path $adapter' in script
