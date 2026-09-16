from __future__ import annotations

import copy
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import bodyrig.photoreal_projection_authority as authority
from bodyrig.photoreal_frame_analyzer_runner import build_analyzer_request
from bodyrig.photoreal_projection_authority import (
    PhotorealProjectionAuthorityError,
    resolve_v2_projection_ambiguity,
)
from bodyrig.photoreal_scan_plan import PhotorealScanPlanError, build_scan_plan
from bodyrig.photoreal_wsl_request_bridge import rewrite_request_transport_paths


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "tools" / "photoreal_reference_vision_adapter_mesh.py"
SPEC = importlib.util.spec_from_file_location("bodyrig_photoreal_mesh_custom_adapter_test", ADAPTER_PATH)
assert SPEC is not None and SPEC.loader is not None
adapter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = adapter
SPEC.loader.exec_module(adapter)


def _plan() -> dict[str, object]:
    train = {
        "kind": "video",
        "source_id": "scene:s1:E:/custom.mp4",
        "group_id": "scene:s1",
        "path": "E:/custom.mp4",
        "information_score": 100.0,
        "projection": "projection-ambiguous-2to1",
        "stereo_layout": "unknown",
        "width": 4096,
        "height": 4096,
        "duration_seconds": 60.0,
        "frame_rate": 60.0,
        "performer_count": 1,
        "source_binding": "scene-performer",
    }
    evaluation = copy.deepcopy(train)
    evaluation.update(
        {
            "source_id": "scene:s2:E:/evaluation.mp4",
            "group_id": "scene:s2",
            "path": "E:/evaluation.mp4",
            "projection": "flat",
            "stereo_layout": "mono",
            "width": 3840,
            "height": 2160,
        }
    )
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": [train],
        "evaluation": [evaluation],
        "identity_bootstrap_policy": "train-only-single-performer-direct-binding-v1",
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt(plan: dict[str, object]) -> dict[str, object]:
    sources = []
    for split in ("train", "evaluation"):
        for index, item in enumerate(plan[split]):
            sources.append(
                {
                    "kind": item["kind"],
                    "source_id": str(item["source_id"]).split(":", 2)[1],
                    "source_key": item["source_id"],
                    "resolved_path": f"/verified/{split}-{index}.mp4",
                    "sha256": ("a" if split == "train" else "b") * 64,
                }
            )
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "sources": sources,
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _probe() -> dict[str, object]:
    return {
        "probe_status": "parsed-isobmff",
        "st3d_present": True,
        "st3d_version": 0,
        "st3d_flags": 0,
        "stereo_mode": "stereo-custom",
        "sv3d_present": True,
        "proj_present": True,
        "projection_type": "mshp",
        "prhd_present": True,
        "prhd_version": 0,
        "prhd_flags": 0,
        "projection_pose_yaw_degrees": 0.0,
        "projection_pose_pitch_degrees": 0.0,
        "projection_pose_roll_degrees": 0.0,
        "projection_data_version": 0,
        "projection_data_flags": 0,
        "mesh_projection_crc32_matches": True,
        "mesh_projection_encoding_supported": True,
        "mesh_projection_crc32": "1a2b3c4d",
        "mesh_projection_encoding": "raw ",
        "mesh_projection_payload_bytes": 128,
    }


def _geometry(mesh_count: int = 2) -> dict[str, object]:
    return {
        "projection_data_version": 0,
        "projection_data_flags": 0,
        "mesh_projection_crc32_matches": True,
        "mesh_projection_crc32": "1a2b3c4d",
        "encoding": "raw ",
        "encoded_payload_bytes": 128,
        "decompressed_payload_sha256": "c" * 64,
        "mesh_count": mesh_count,
        "total_vertex_count": 84 if mesh_count == 2 else 42,
        "total_index_count": 240 if mesh_count == 2 else 120,
        "texture_ids": [0],
        "index_types": [0, 1],
        "unknown_box_types": [],
    }


def _install(monkeypatch: pytest.MonkeyPatch, *, mesh_count: int = 2) -> None:
    monkeypatch.setattr(authority, "probe_isobmff_file", lambda _path: _probe())
    monkeypatch.setattr(
        authority,
        "parse_mesh_projection_file",
        lambda _path, materialize=False: _geometry(mesh_count),
    )


def _resolved_scan(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
    plan = _plan()
    receipt = _receipt(plan)
    _install(monkeypatch, mesh_count=2)
    resolved, _ = resolve_v2_projection_ambiguity(plan, receipt)
    return build_scan_plan(resolved, receipt)


def test_two_mesh_stereo_custom_becomes_mesh_custom_and_stays_pretraining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    _install(monkeypatch, mesh_count=2)

    resolved, count = resolve_v2_projection_ambiguity(plan, receipt)
    assert count == 1
    train = resolved["train"][0]
    assert train["projection"] == "mshp"
    assert train["stereo_layout"] == "mesh-custom"
    assert train["projection_authority"]["mesh_projection_mesh_count"] == 2
    assert train["projection_authority"]["deprojection_authority"] is False

    scan = build_scan_plan(resolved, receipt)
    source = next(item for item in scan["sources"] if item["source_key"].startswith("scene:s1:"))
    assert source["stereo_layout"] == "mesh-custom"
    assert source["decode_mode"] == "spatial-deprojection-required"
    assert {item["eye"] for item in source["samples"]} == {"left", "right"}
    assert source["identity_bootstrap_eligible"] is False
    assert scan["teacher_training_authorized"] is False
    assert scan["production_activation"] is False


def test_stereo_custom_refuses_single_mesh_even_when_header_is_valid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    receipt = _receipt(plan)
    _install(monkeypatch, mesh_count=1)
    with pytest.raises(PhotorealProjectionAuthorityError, match="unsupported Spherical V2 stereo mode"):
        resolve_v2_projection_ambiguity(plan, receipt)


def test_scan_plan_refuses_mesh_custom_without_two_mesh_authority() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    train = plan["train"][0]
    train["projection"] = "mshp"
    train["stereo_layout"] = "mesh-custom"
    train["projection_authority"] = {
        "format": "bodyrig-spherical-v2-projection-authority",
        "version": 1,
        "projection_type": "mshp",
        "mesh_projection_mesh_count": 1,
        "deprojection_authority": False,
    }
    with pytest.raises(PhotorealScanPlanError, match="authoritative two-mesh"):
        build_scan_plan(plan, receipt)


def test_mesh_custom_decoder_uses_full_frame_but_preserves_eye_for_mesh_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_image = object()
    calls: list[tuple[dict[str, object], dict[str, object]]] = []

    def read_sample(_runtime, source, sample):
        calls.append((dict(source), dict(sample)))
        return raw_image, True

    monkeypatch.setattr(adapter.base, "_read_sample", read_sample)
    source = {
        "projection": "mshp",
        "stereo_layout": "mesh-custom",
        "decode_mode": "spatial-deprojection-required",
    }
    sample = {"timestamp_seconds": 1.0, "eye": "right"}
    image, spatial = adapter._read_frame_sample(SimpleNamespace(), source, sample)

    assert image is raw_image and spatial is True
    assert len(calls) == 1
    assert calls[0][0]["stereo_layout"] == "mono"
    assert calls[0][1]["eye"] == "mono"
    assert source["stereo_layout"] == "mesh-custom"
    assert sample["eye"] == "right"


def test_mesh_custom_decoder_refuses_non_mesh_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        adapter.base,
        "_read_sample",
        lambda *_args: (_ for _ in ()).throw(AssertionError("base decoder must not be called")),
    )
    with pytest.raises(adapter.ReferenceVisionError, match="authoritative mshp"):
        adapter._read_frame_sample(
            SimpleNamespace(),
            {"projection": "equi", "stereo_layout": "mesh-custom"},
            {"timestamp_seconds": 1.0, "eye": "left"},
        )


def test_analyzer_request_preserves_mesh_custom_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    scan = _resolved_scan(monkeypatch)
    request = build_analyzer_request(
        scan,
        adapter="bodyrig-reference-vision-v1",
        revision="r1",
        model_set_sha256="d" * 64,
    )
    source = next(item for item in request["sources"] if item["source_key"].startswith("scene:s1:"))
    assert source["stereo_layout"] == "mesh-custom"
    assert source["projection"] == "mshp"
    assert source["projection_authority"]["mesh_projection_mesh_count"] == 2
    assert source["projection_authority"]["deprojection_authority"] is False
    assert request["identity_matching_authority"] is False
    assert request["photoreal_acceptance_authority"] is False
    assert request["production_activation"] is False


def test_wsl_transport_changes_only_mesh_custom_resolved_path(monkeypatch: pytest.MonkeyPatch) -> None:
    scan = _resolved_scan(monkeypatch)
    request = build_analyzer_request(
        scan,
        adapter="bodyrig-reference-vision-v1",
        revision="r1",
        model_set_sha256="d" * 64,
    )
    translated = rewrite_request_transport_paths(request, lambda value: "/mnt/verified/" + Path(value).name)
    original = next(item for item in request["sources"] if item["source_key"].startswith("scene:s1:"))
    transported = next(item for item in translated["sources"] if item["source_key"] == original["source_key"])
    assert transported["resolved_path"] != original["resolved_path"]
    assert transported["stereo_layout"] == original["stereo_layout"] == "mesh-custom"
    assert transported["projection_authority"] == original["projection_authority"]
    assert transported["samples"] == original["samples"]


def test_scan_plan_schema_exposes_only_explicit_mesh_custom_layout() -> None:
    schema = json.loads((ROOT / "contracts" / "photoreal-scan-plan-v1.schema.json").read_text(encoding="utf-8"))
    values = schema["$defs"]["source"]["properties"]["stereo_layout"]["enum"]
    assert values == ["mono", "side-by-side", "over-under", "mesh-custom"]
