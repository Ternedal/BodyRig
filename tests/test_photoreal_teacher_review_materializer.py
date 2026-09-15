from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_teacher_review_materializer import (
    PhotorealTeacherReviewMaterializerError,
    build_materialization_request,
    build_materializer_config,
    validate_materialization_result,
)


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _catalog(*, projection: str = "flat", stereo_layout: str = "mono", eye: str = "mono") -> dict[str, object]:
    observation_id = "c" * 64
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-held-out-reference-catalog",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "held_out_source_count": 1,
        "held_out_observation_count": 1,
        "held_out_sources": [{
            "source_key": "scene:eval:E:/eval.mp4",
            "group_id": "scene:eval",
            "kind": "video",
            "resolved_path": r"\\stash\VR_E\eval.mp4",
            "size_bytes": 1000,
            "sha256": "d" * 64,
            "width": 3840,
            "height": 2160,
            "projection": projection,
            "stereo_layout": stereo_layout,
        }],
        "held_out_observations": [{
            "observation_id": observation_id,
            "source_key": "scene:eval:E:/eval.mp4",
            "group_id": "scene:eval",
            "frame_sha256": "e" * 64,
            "timestamp_seconds": 2.0,
            "eye": eye,
            "view_bin": "front",
            "coverage": ["face-front", "full-body-front"],
            "reference_bytes_materialized": False,
            "reference_frame_hash_verified": False,
        }],
        "required_coverage": ["face-front", "full-body-front"],
        "observed_coverage": ["face-front", "full-body-front"],
        "coverage_candidates": [
            {"coverage": "face-front", "candidate_observation_ids": [observation_id], "candidate_count": 1, "human_reference_selection_required": True},
            {"coverage": "full-body-front", "candidate_observation_ids": [observation_id], "candidate_count": 1, "human_reference_selection_required": True},
        ],
        "coverage_authority": "core-frame-index-v1",
        "teacher_process_disclosure": False,
        "source_paths_build_private": True,
        "reference_bytes_materialized": False,
        "reference_frame_hashes_verified": False,
        "human_reference_selection_required": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["held_out_reference_catalog_sha256"] = _digest(value, "held_out_reference_catalog_sha256")
    return value


def _mapping(catalog: dict[str, object]) -> dict[str, object]:
    observation_id = "c" * 64
    source = catalog["held_out_sources"][0]
    observation = catalog["held_out_observations"][0]
    mappings = []
    for coverage, orbit in (("face-front", 25), ("full-body-front", 25)):
        mappings.append({
            "coverage": coverage,
            "render_orbit_index": orbit,
            "render_relative_path": "review/neutral-pose/25.png",
            "render_sha256": "f" * 64,
            "render_camera": {"orbit_index": orbit},
            "reference_observation_id": observation_id,
            "reference_source_key": source["source_key"],
            "reference_source_resolved_path": source["resolved_path"],
            "reference_source_sha256": source["sha256"],
            "reference_frame_sha256": observation["frame_sha256"],
            "reference_timestamp_seconds": observation["timestamp_seconds"],
            "reference_eye": observation["eye"],
            "reference_view_bin": observation["view_bin"],
            "reference_coverage": observation["coverage"],
            "reference_bytes_materialized": False,
            "reference_frame_hash_verified": False,
        })
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-review-mapping",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "review_render_set_sha256": "b" * 64,
        "held_out_reference_catalog_sha256": catalog["held_out_reference_catalog_sha256"],
        "reviewer": "operator",
        "operator_supplied": True,
        "mapping_count": 2,
        "mappings": mappings,
        "semantic_view_mapping_complete": True,
        "semantic_view_authority": "human-operator-mapping-v1",
        "reference_selection_complete": True,
        "reference_selection_authority": "human-operator-selection-v1",
        "reference_bytes_materialized": False,
        "reference_frame_hashes_verified": False,
        "likeness_review_complete": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["review_mapping_sha256"] = _digest(value, "review_mapping_sha256")
    return value


def test_materialization_request_deduplicates_one_reference_used_by_multiple_coverages() -> None:
    catalog = _catalog()
    request = build_materialization_request(
        _mapping(catalog), catalog, adapter="bodyrig-reference-frame-materializer-v1", revision="1" * 64
    )

    assert request["source_count"] == 1
    assert request["sample_count"] == 1
    sample = request["sources"][0]["samples"][0]
    assert sample["observation_id"] == "c" * 64
    assert sample["coverages"] == ["face-front", "full-body-front"]
    assert sample["expected_frame_sha256"] == "e" * 64
    assert request["decode_semantics"] == "opencv-bgr-array-v1"
    assert request["frame_hash_semantics"] == "sha256(shape-ascii-newline+contiguous-bgr-bytes)"
    assert request["photoreal_acceptance_authority"] is False
    assert request["production_activation"] is False


def test_materialization_request_preserves_sbs_eye_decode_authority() -> None:
    catalog = _catalog(stereo_layout="side-by-side", eye="left")
    request = build_materialization_request(
        _mapping(catalog), catalog, adapter="bodyrig-reference-frame-materializer-v1", revision="1" * 64
    )
    source = request["sources"][0]
    assert source["stereo_layout"] == "side-by-side"
    assert source["samples"][0]["eye"] == "left"


def test_materialization_request_rejects_spatial_projection_until_exact_deprojection_is_reused() -> None:
    catalog = _catalog(projection="vr180", stereo_layout="side-by-side", eye="left")
    with pytest.raises(PhotorealTeacherReviewMaterializerError, match="reproducible flat projection"):
        build_materialization_request(
            _mapping(catalog), catalog, adapter="bodyrig-reference-frame-materializer-v1", revision="1" * 64
        )


def test_materialization_request_rejects_mapping_catalog_source_tamper() -> None:
    catalog = _catalog()
    mapping = _mapping(catalog)
    mapping["mappings"][0]["reference_source_sha256"] = "9" * 64
    mapping["review_mapping_sha256"] = _digest(mapping, "review_mapping_sha256")
    with pytest.raises(PhotorealTeacherReviewMaterializerError, match="reference_source_sha256"):
        build_materialization_request(
            mapping, catalog, adapter="bodyrig-reference-frame-materializer-v1", revision="1" * 64
        )


def test_materialization_request_rejects_stale_mapping_digest() -> None:
    catalog = _catalog()
    mapping = _mapping(catalog)
    mapping["reviewer"] = "tampered"
    with pytest.raises(PhotorealTeacherReviewMaterializerError, match="mapping digest mismatch"):
        build_materialization_request(
            mapping, catalog, adapter="bodyrig-reference-frame-materializer-v1", revision="1" * 64
        )


def test_materializer_config_pins_exact_adapter_bytes(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    bridge = tmp_path / "bridge.py"
    adapter = tmp_path / "adapter.py"
    python.write_text("python", encoding="utf-8")
    bridge.write_text("bridge", encoding="utf-8")
    adapter.write_text("exact-adapter", encoding="utf-8")

    result = build_materializer_config(
        windows_python=python,
        bridge_path=bridge,
        adapter_path=adapter,
    )

    assert result["adapter"] == "bodyrig-reference-frame-materializer-v1"
    assert result["revision"] == hashlib.sha256(b"exact-adapter").hexdigest()
    assert str(bridge.resolve()) in result["command"]
    assert str(adapter.resolve()) in result["command"]


def test_materialization_result_revalidates_exact_png_universe(tmp_path: Path) -> None:
    catalog = _catalog()
    mapping = _mapping(catalog)
    request = build_materialization_request(
        mapping, catalog, adapter="bodyrig-reference-frame-materializer-v1", revision="1" * 64
    )
    output = tmp_path / "output"
    refs = output / "references"
    refs.mkdir(parents=True)
    observation_id = "c" * 64
    png = refs / f"{observation_id}.png"
    png.write_bytes(b"review-reference-png")
    receipt = {
        "format": "bodyrig-photoreal-reference-frame-materialization-receipt",
        "version": 1,
        "performer_id": request["performer_id"],
        "selected_epoch_id": request["selected_epoch_id"],
        "teacher_input_sha256": request["teacher_input_sha256"],
        "review_mapping_sha256": request["review_mapping_sha256"],
        "held_out_reference_catalog_sha256": request["held_out_reference_catalog_sha256"],
        "adapter": request["adapter"],
        "revision": request["revision"],
        "source_count": 1,
        "sample_count": 1,
        "materialized_references": [{
            "observation_id": observation_id,
            "source_key": "scene:eval:E:/eval.mp4",
            "expected_frame_sha256": "e" * 64,
            "observed_frame_sha256": "e" * 64,
            "timestamp_seconds": 2.0,
            "eye": "mono",
            "coverages": ["face-front", "full-body-front"],
            "source_hash_verified": True,
            "frame_hash_verified": True,
            "png_relative_path": f"references/{observation_id}.png",
            "png_size_bytes": png.stat().st_size,
            "png_sha256": hashlib.sha256(png.read_bytes()).hexdigest(),
        }],
        "all_source_hashes_verified": True,
        "all_frame_hashes_verified": True,
        "decode_semantics": request["decode_semantics"],
        "frame_hash_semantics": request["frame_hash_semantics"],
        "teacher_process_disclosure": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }

    result = validate_materialization_result(receipt, request=request, output_dir=output)
    assert result["all_frame_hashes_verified"] is True
    assert result["materialized_references"][0]["png_sha256"] == hashlib.sha256(png.read_bytes()).hexdigest()

    extra = refs / "extra.png"
    extra.write_bytes(b"extra")
    with pytest.raises(PhotorealTeacherReviewMaterializerError, match="PNG universe mismatch"):
        validate_materialization_result(receipt, request=request, output_dir=output)
