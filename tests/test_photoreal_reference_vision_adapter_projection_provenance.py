from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "tools" / "photoreal_reference_vision_adapter.py"


def _load_adapter():
    module_name = "bodyrig_photoreal_reference_vision_adapter_projection_test"
    spec = importlib.util.spec_from_file_location(module_name, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _explicit_equi_authority() -> dict[str, object]:
    return {
        "format": "bodyrig-explicit-projection-authority",
        "version": 1,
        "projection_type": "equi",
        "pose_degrees": {"yaw": 0.0, "pitch": 0.0, "roll": 0.0},
        "equirectangular_bounds_fraction": {
            "top": 0.0,
            "bottom": 0.0,
            "left": 0.25,
            "right": 0.25,
        },
        "cubemap_layout": None,
        "cubemap_padding_pixels": None,
        "mesh_projection_crc32": None,
        "mesh_projection_encoding": None,
        "mesh_projection_payload_bytes": None,
        "mesh_projection_geometry_sha256": None,
        "mesh_projection_mesh_count": None,
        "mesh_projection_total_vertex_count": None,
        "mesh_projection_total_index_count": None,
        "mesh_projection_texture_ids": None,
        "mesh_projection_index_types": None,
        "mesh_projection_unknown_box_types": None,
        "deprojection_authority": False,
    }


def test_frame_adapter_forwards_explicit_equi_authority_to_deprojector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _load_adapter()
    authority = _explicit_equi_authority()
    decoded_image = object()
    viewport_image = object()
    observed: dict[str, object] = {}

    monkeypatch.setattr(adapter, "_read_sample", lambda _runtime, _source, _sample: (decoded_image, True))

    def fake_deproject(runtime, image, projection_authority):
        observed["runtime"] = runtime
        observed["image"] = image
        observed["projection_authority"] = projection_authority
        return [("v00", viewport_image)]

    monkeypatch.setattr(adapter, "deproject_equirectangular_views", fake_deproject)

    def fake_candidate_rows(runtime, image, *, base, candidate_prefix=""):
        observed["candidate_runtime"] = runtime
        observed["viewport_image"] = image
        observed["base"] = dict(base)
        observed["candidate_prefix"] = candidate_prefix
        return [{"candidate_id": f"{candidate_prefix}person-000"}]

    monkeypatch.setattr(adapter, "_candidate_rows", fake_candidate_rows)

    runtime = object()
    source = {
        "source_key": "scene:s1:E:/vr180.mp4",
        "source_sha256": "a" * 64,
        "kind": "video",
        "projection": "equi",
        "projection_authority": authority,
        "samples": [{"timestamp_seconds": 12.5, "eye": "left"}],
    }
    request = {"performer_id": "42", "sources": [source]}
    args = SimpleNamespace(
        bodyrig_adapter="bodyrig-reference-vision-v1",
        bodyrig_revision="b" * 64,
        bodyrig_model_set_sha256="c" * 64,
    )

    result = adapter._frame_result(runtime, request, args)

    assert observed["runtime"] is runtime
    assert observed["image"] is decoded_image
    assert observed["projection_authority"] is authority
    assert observed["viewport_image"] is viewport_image
    assert observed["candidate_prefix"] == "v00-"
    assert observed["base"]["projection"] == "equi"
    assert result["format"] == "bodyrig-photoreal-frame-observations"
    assert result["observations"] == [{"candidate_id": "v00-person-000"}]
    assert result["production_activation"] is False
