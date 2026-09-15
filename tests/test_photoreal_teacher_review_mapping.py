from __future__ import annotations

import copy
import hashlib
import json

import pytest

from bodyrig.photoreal_teacher_review_mapping import (
    PhotorealTeacherReviewMappingError,
    build_review_mapping,
)


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    ).hexdigest()


def _render_set() -> dict[str, object]:
    renders = [
        {
            "relative_path": f"review/neutral-pose/{index}.png",
            "size_bytes": 1000 + index,
            "sha256": format(index % 16, "x") * 64,
            "camera": {"orbit_index": index, "azimuth_degrees_normalized": float((180 + 7.2 * index) % 360)},
            "semantic_view_label": None,
            "semantic_view_authority": False,
            "human_semantic_view_mapping_required": True,
        }
        for index in range(50)
    ]
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-review-render-set",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "teacher_manifest_sha256": "b" * 64,
        "adapter": "exavatar-benchmark",
        "upstream_repository": "https://github.com/mks0601/ExAvatar_RELEASE",
        "upstream_commit": "d45268730c779fae4118f1a361cf9ff639bc4d1e",
        "camera_calibration_source": "avatar/main/get_neutral_pose.py",
        "camera_calibration_formula": "azim=pi+2*pi*i/50;elev=-pi/6;view_num=50",
        "render_count": 50,
        "renders": renders,
        "render_bytes_verified": True,
        "camera_geometry_authority": True,
        "semantic_view_authority": False,
        "human_semantic_view_mapping_required": True,
        "held_out_reference_binding_present": False,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["review_render_set_sha256"] = _digest(value, "review_render_set_sha256")
    return value


def _reference_catalog() -> dict[str, object]:
    obs_front = "c" * 64
    obs_three = "d" * 64
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-held-out-reference-catalog",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "held_out_source_count": 1,
        "held_out_observation_count": 2,
        "held_out_sources": [{
            "source_key": "scene:eval:E:/eval.mp4",
            "group_id": "scene:eval",
            "kind": "video",
            "resolved_path": r"\\stash\VR_E\eval.mp4",
            "size_bytes": 1000,
            "sha256": "e" * 64,
            "width": 3840,
            "height": 2160,
            "projection": "flat",
            "stereo_layout": "mono",
        }],
        "held_out_observations": [
            {
                "observation_id": obs_front,
                "source_key": "scene:eval:E:/eval.mp4",
                "group_id": "scene:eval",
                "frame_sha256": "1" * 64,
                "timestamp_seconds": 2.0,
                "eye": "mono",
                "view_bin": "front",
                "coverage": ["face-front", "full-body-front"],
                "reference_bytes_materialized": False,
                "reference_frame_hash_verified": False,
            },
            {
                "observation_id": obs_three,
                "source_key": "scene:eval:E:/eval.mp4",
                "group_id": "scene:eval",
                "frame_sha256": "2" * 64,
                "timestamp_seconds": 3.0,
                "eye": "mono",
                "view_bin": "three-quarter-left",
                "coverage": ["face-three-quarter", "full-body-three-quarter"],
                "reference_bytes_materialized": False,
                "reference_frame_hash_verified": False,
            },
        ],
        "required_coverage": ["face-front", "face-three-quarter", "full-body-front", "full-body-three-quarter"],
        "observed_coverage": ["face-front", "face-three-quarter", "full-body-front", "full-body-three-quarter"],
        "coverage_candidates": [
            {"coverage": "face-front", "candidate_observation_ids": [obs_front], "candidate_count": 1, "human_reference_selection_required": True},
            {"coverage": "face-three-quarter", "candidate_observation_ids": [obs_three], "candidate_count": 1, "human_reference_selection_required": True},
            {"coverage": "full-body-front", "candidate_observation_ids": [obs_front], "candidate_count": 1, "human_reference_selection_required": True},
            {"coverage": "full-body-three-quarter", "candidate_observation_ids": [obs_three], "candidate_count": 1, "human_reference_selection_required": True},
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


def _selection() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-teacher-review-selection-input",
        "version": 1,
        "reviewer": "operator",
        "operator_supplied": True,
        "selections": [
            {"coverage": "face-front", "render_orbit_index": 25, "reference_observation_id": "c" * 64},
            {"coverage": "face-three-quarter", "render_orbit_index": 31, "reference_observation_id": "d" * 64},
            {"coverage": "full-body-front", "render_orbit_index": 25, "reference_observation_id": "c" * 64},
            {"coverage": "full-body-three-quarter", "render_orbit_index": 31, "reference_observation_id": "d" * 64},
        ],
    }


def test_review_mapping_records_human_semantic_and_reference_selection_without_likeness_pass() -> None:
    result = build_review_mapping(_render_set(), _reference_catalog(), _selection())

    assert result["mapping_count"] == 4
    assert result["semantic_view_mapping_complete"] is True
    assert result["semantic_view_authority"] == "human-operator-mapping-v1"
    assert result["reference_selection_complete"] is True
    assert result["reference_bytes_materialized"] is False
    assert result["reference_frame_hashes_verified"] is False
    assert result["likeness_review_complete"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_review_mapping_rejects_reference_not_authorized_for_coverage() -> None:
    selection = _selection()
    selection["selections"][0]["reference_observation_id"] = "d" * 64

    with pytest.raises(PhotorealTeacherReviewMappingError, match="not a candidate for coverage"):
        build_review_mapping(_render_set(), _reference_catalog(), selection)


def test_review_mapping_requires_every_required_coverage() -> None:
    selection = _selection()
    selection["selections"].pop()

    with pytest.raises(PhotorealTeacherReviewMappingError, match="cover required semantic views exactly"):
        build_review_mapping(_render_set(), _reference_catalog(), selection)


def test_review_mapping_rejects_cross_lineage_render_and_reference_sets() -> None:
    references = _reference_catalog()
    references["selected_epoch_id"] = "epoch-b"
    references["held_out_reference_catalog_sha256"] = _digest(references, "held_out_reference_catalog_sha256")

    with pytest.raises(PhotorealTeacherReviewMappingError, match="lineage mismatch"):
        build_review_mapping(_render_set(), references, _selection())


def test_review_mapping_rejects_tampered_render_set_digest() -> None:
    renders = _render_set()
    renders["renders"][0]["size_bytes"] = 999999

    with pytest.raises(PhotorealTeacherReviewMappingError, match="digest mismatch"):
        build_review_mapping(renders, _reference_catalog(), _selection())
