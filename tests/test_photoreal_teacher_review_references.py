from __future__ import annotations

import copy
import hashlib
import json

import pytest

from bodyrig.photoreal_teacher_review_references import (
    PhotorealTeacherReviewReferenceError,
    build_held_out_reference_catalog,
)


def _digest(value: dict[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _source(key: str, group: str, path: str, sha: str) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": group,
        "kind": "video",
        "resolved_path": path,
        "size_bytes": 1000,
        "sha256": sha * 64,
        "information_score": 100.0,
        "width": 3840,
        "height": 2160,
        "projection": "flat",
        "stereo_layout": "mono",
    }


def _observation(
    key: str,
    group: str,
    sha: str,
    timestamp: float,
    coverage: list[str],
) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": group,
        "split": "evaluation",
        "frame_sha256": sha * 64,
        "timestamp_seconds": timestamp,
        "eye": "mono",
        "view_bin": "front" if "face-front" in coverage else "three-quarter-left",
        "coverage": coverage,
    }


def _teacher_input() -> dict[str, object]:
    train_key = "scene:train:E:/train.mp4"
    eval_key = "scene:eval:E:/eval.mp4"
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-input",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "selected_epoch_id": "epoch-a",
        "appearance_epoch_selection_sha256": "a" * 64,
        "identity_bank_sha256": "b" * 64,
        "identity_calibration_sha256": "c" * 64,
        "analyzer_model_set_sha256": "d" * 64,
        "training_sources": [_source(train_key, "scene:train", r"\\stash\VR_E\train.mp4", "e")],
        "held_out_evaluation_sources": [_source(eval_key, "scene:eval", r"\\stash\VR_E\eval.mp4", "f")],
        "training_observations": [
            {
                "source_key": train_key,
                "group_id": "scene:train",
                "split": "train",
                "frame_sha256": "1" * 64,
                "timestamp_seconds": 1.0,
                "eye": "mono",
                "view_bin": "front",
                "coverage": ["face-front", "full-body-front"],
            }
        ],
        "held_out_evaluation_observations": [
            _observation(eval_key, "scene:eval", "2", 2.0, ["face-front", "full-body-front"]),
            _observation(eval_key, "scene:eval", "3", 3.0, ["face-three-quarter", "full-body-three-quarter"]),
        ],
        "held_out_view_coverage_required": [
            "face-front",
            "face-three-quarter",
            "full-body-front",
            "full-body-three-quarter",
        ],
        "held_out_view_coverage_observed": [
            "face-front",
            "face-three-quarter",
            "full-body-front",
            "full-body-three-quarter",
        ],
        "held_out_view_coverage_missing": [],
        "training_source_count": 1,
        "held_out_evaluation_source_count": 1,
        "training_observation_count": 1,
        "held_out_evaluation_observation_count": 2,
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["teacher_input_sha256"] = _digest(value)
    return value


def _reseal(value: dict[str, object]) -> None:
    value.pop("teacher_input_sha256", None)
    value["teacher_input_sha256"] = _digest(value)


def test_held_out_reference_catalog_binds_eval_sources_without_disclosing_to_teacher() -> None:
    result = build_held_out_reference_catalog(_teacher_input())

    assert result["held_out_source_count"] == 1
    assert result["held_out_observation_count"] == 2
    assert result["teacher_process_disclosure"] is False
    assert result["source_paths_build_private"] is True
    assert result["reference_bytes_materialized"] is False
    assert result["reference_frame_hashes_verified"] is False
    assert result["human_reference_selection_required"] is True
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False
    assert result["held_out_sources"][0]["resolved_path"] == r"\\stash\VR_E\eval.mp4"
    by_coverage = {item["coverage"]: item for item in result["coverage_candidates"]}
    assert by_coverage["face-front"]["candidate_count"] == 1
    assert by_coverage["face-three-quarter"]["candidate_count"] == 1
    assert all(len(item["observation_id"]) == 64 for item in result["held_out_observations"])


def test_held_out_reference_catalog_rejects_stale_teacher_input_digest() -> None:
    value = _teacher_input()
    value["held_out_evaluation_sources"][0]["resolved_path"] = r"\\stash\VR_E\substituted.mp4"

    with pytest.raises(PhotorealTeacherReviewReferenceError, match="SHA-256 does not match"):
        build_held_out_reference_catalog(value)


def test_held_out_reference_catalog_rejects_boolean_v1_even_when_resealed() -> None:
    value = _teacher_input()
    value["version"] = True
    _reseal(value)

    with pytest.raises(PhotorealTeacherReviewReferenceError, match="numeric v1"):
        build_held_out_reference_catalog(value)


def test_held_out_reference_catalog_rejects_required_coverage_without_candidate() -> None:
    value = copy.deepcopy(_teacher_input())
    value["held_out_view_coverage_required"].append("face-profile")
    value["held_out_view_coverage_observed"].append("face-profile")
    _reseal(value)

    with pytest.raises(PhotorealTeacherReviewReferenceError, match="no reference candidates"):
        build_held_out_reference_catalog(value)
