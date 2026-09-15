from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_animated_review_authority import (
    PhotorealAnimatedReviewAuthorityError,
    validate_motion_reference_catalog,
)
from bodyrig.photoreal_animated_review_plan import (
    MOTION_REVIEW_DIMENSIONS,
    PhotorealAnimatedReviewPlanError,
    build_animated_review_plan,
)
from bodyrig.photoreal_animation_execution_receipt import build_animation_execution_receipt
from bodyrig.photoreal_animation_plan import ANIMATION_REQUIREMENTS


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _observation_id(*, source_key: str, frame_sha: str, timestamp: float | None, eye: str) -> str:
    payload = {
        "source_key": source_key,
        "frame_sha256": frame_sha,
        "timestamp_seconds": timestamp,
        "eye": eye,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _animation_execution(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    output = tmp_path / "animation-output"
    artifact = output / "animation" / "motion.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"exact-animated-teacher-evidence")
    raw = {
        "format": "bodyrig-photoreal-animation-manifest",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "teacher_manifest_sha256": "b" * 64,
        "static_teacher_review_sha256": "c" * 64,
        "animation_plan_sha256": "d" * 64,
        "adapter": "test-animation-adapter",
        "adapter_revision": "revision-a",
        "representation": "animated-teacher",
        "animation_complete": True,
        "consumed_teacher_artifacts": [
            {"relative_path": "checkpoint/teacher.bin", "sha256": "e" * 64}
        ],
        "implemented_validation_dimensions": list(ANIMATION_REQUIREMENTS),
        "animation_artifacts": [
            {
                "kind": "animated-review-media",
                "relative_path": "animation/motion.bin",
                "size_bytes": artifact.stat().st_size,
                "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            }
        ],
        "animated_teacher_acceptance_authority": False,
        "human_animated_visual_acceptance_required": True,
        "p3_device_distillation_authorized": False,
        "production_activation": False,
    }
    return output, build_animation_execution_receipt(raw)


def _catalog(*, kind: str = "video", timestamp: float | None = 12.0) -> dict[str, object]:
    source_key = "scene:eval:E:/held-out.mp4"
    frame_sha = "f" * 64
    observation_id = _observation_id(
        source_key=source_key,
        frame_sha=frame_sha,
        timestamp=timestamp,
        eye="mono",
    )
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-teacher-held-out-reference-catalog",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "held_out_source_count": 1,
        "held_out_observation_count": 1,
        "held_out_sources": [
            {
                "source_key": source_key,
                "group_id": "eval-group",
                "kind": kind,
                "resolved_path": r"\\stash\VR_E\held-out.mp4",
                "size_bytes": 123456,
                "sha256": "1" * 64,
                "width": 3840,
                "height": 2160,
                "projection": "flat",
                "stereo_layout": "mono",
            }
        ],
        "held_out_observations": [
            {
                "observation_id": observation_id,
                "source_key": source_key,
                "group_id": "eval-group",
                "frame_sha256": frame_sha,
                "timestamp_seconds": timestamp,
                "eye": "mono",
                "view_bin": "front",
                "coverage": ["face-front", "full-body-front"],
                "reference_bytes_materialized": False,
                "reference_frame_hash_verified": False,
            }
        ],
        "required_coverage": ["face-front"],
        "observed_coverage": ["face-front", "full-body-front"],
        "coverage_candidates": [
            {
                "coverage": "face-front",
                "candidate_observation_ids": [observation_id],
                "candidate_count": 1,
                "human_reference_selection_required": True,
            }
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
    value["held_out_reference_catalog_sha256"] = _digest(
        value, "held_out_reference_catalog_sha256"
    )
    return value


def _selection(catalog: dict[str, object]) -> dict[str, object]:
    observation_id = catalog["held_out_observations"][0]["observation_id"]
    return {
        "format": "bodyrig-photoreal-animated-review-selection-input",
        "version": 1,
        "reviewer": "operator",
        "operator_supplied": True,
        "selections": [
            {
                "dimension": dimension,
                "animation_artifact_relative_path": "animation/motion.bin",
                "reference_observation_id": observation_id,
                "window_before_seconds": 1.0,
                "window_after_seconds": 1.5,
            }
            for dimension in MOTION_REVIEW_DIMENSIONS
        ],
    }


def test_valid_human_selected_motion_review_plan_stays_non_accepting(tmp_path: Path) -> None:
    animation_root, execution = _animation_execution(tmp_path)
    catalog = _catalog()
    validate_motion_reference_catalog(catalog)
    result = build_animated_review_plan(
        execution,
        catalog,
        _selection(catalog),
        animation_output_root=animation_root,
    )
    assert result["motion_review_dimensions"] == list(MOTION_REVIEW_DIMENSIONS)
    assert result["selection_count"] == len(MOTION_REVIEW_DIMENSIONS)
    assert result["animation_artifact_bytes_reverified"] is True
    assert result["held_out_evaluation_only"] is True
    assert result["held_out_motion_reference_selection_complete"] is True
    assert result["reference_motion_bytes_materialized"] is False
    assert result["animated_teacher_acceptance_authority"] is False
    assert result["p3_device_distillation_authorized"] is False
    assert result["production_activation"] is False
    assert all(item["window_start_seconds"] == 11.0 for item in result["selections"])
    assert all(item["window_end_seconds"] == 13.5 for item in result["selections"])


def test_motion_review_plan_rejects_duplicate_dimension_and_missing_dimension(tmp_path: Path) -> None:
    animation_root, execution = _animation_execution(tmp_path)
    catalog = _catalog()
    selection = _selection(catalog)
    selection["selections"][-1]["dimension"] = MOTION_REVIEW_DIMENSIONS[0]
    with pytest.raises(PhotorealAnimatedReviewPlanError, match="repeats motion-review dimension"):
        build_animated_review_plan(execution, catalog, selection, animation_output_root=animation_root)


def test_motion_review_plan_rejects_still_image_as_motion_evidence(tmp_path: Path) -> None:
    animation_root, execution = _animation_execution(tmp_path)
    catalog = _catalog(kind="image")
    with pytest.raises(PhotorealAnimatedReviewPlanError, match="must come from held-out video"):
        build_animated_review_plan(
            execution, catalog, _selection(catalog), animation_output_root=animation_root
        )


def test_motion_review_plan_rejects_null_timestamp_even_on_video(tmp_path: Path) -> None:
    animation_root, execution = _animation_execution(tmp_path)
    catalog = _catalog(timestamp=None)
    with pytest.raises(PhotorealAnimatedReviewPlanError, match="requires a video timestamp"):
        build_animated_review_plan(
            execution, catalog, _selection(catalog), animation_output_root=animation_root
        )


def test_motion_review_plan_rejects_unknown_observation(tmp_path: Path) -> None:
    animation_root, execution = _animation_execution(tmp_path)
    catalog = _catalog()
    selection = _selection(catalog)
    selection["selections"][0]["reference_observation_id"] = "9" * 64
    with pytest.raises(PhotorealAnimatedReviewPlanError, match="outside reference catalog"):
        build_animated_review_plan(execution, catalog, selection, animation_output_root=animation_root)


def test_motion_review_plan_rejects_animation_artifact_byte_drift(tmp_path: Path) -> None:
    animation_root, execution = _animation_execution(tmp_path)
    catalog = _catalog()
    (animation_root / "animation" / "motion.bin").write_bytes(b"changed-after-execution-receipt")
    with pytest.raises(PhotorealAnimatedReviewPlanError, match="size drifted|bytes drifted"):
        build_animated_review_plan(
            execution, catalog, _selection(catalog), animation_output_root=animation_root
        )


def test_motion_reference_authority_rejects_catalog_digest_tamper() -> None:
    catalog = _catalog()
    catalog["held_out_sources"][0]["resolved_path"] = r"\\stash\VR_E\different.mp4"
    with pytest.raises(PhotorealAnimatedReviewAuthorityError, match="SHA-256 does not match content"):
        validate_motion_reference_catalog(catalog)


def test_motion_reference_authority_recomputes_observation_id_even_if_catalog_is_resealed() -> None:
    catalog = _catalog()
    catalog["held_out_observations"][0]["observation_id"] = "9" * 64
    catalog["coverage_candidates"][0]["candidate_observation_ids"] = ["9" * 64]
    catalog["held_out_reference_catalog_sha256"] = _digest(
        catalog, "held_out_reference_catalog_sha256"
    )
    with pytest.raises(PhotorealAnimatedReviewAuthorityError, match="observation id does not match"):
        validate_motion_reference_catalog(catalog)


def test_motion_review_plan_rejects_execution_catalog_lineage_mismatch(tmp_path: Path) -> None:
    animation_root, execution = _animation_execution(tmp_path)
    catalog = _catalog()
    catalog["performer_id"] = "43"
    catalog["held_out_reference_catalog_sha256"] = _digest(
        catalog, "held_out_reference_catalog_sha256"
    )
    validate_motion_reference_catalog(catalog)
    with pytest.raises(PhotorealAnimatedReviewPlanError, match="lineage do not match"):
        build_animated_review_plan(
            execution, catalog, _selection(catalog), animation_output_root=animation_root
        )


def test_motion_review_plan_rejects_boolean_selection_version(tmp_path: Path) -> None:
    animation_root, execution = _animation_execution(tmp_path)
    catalog = _catalog()
    selection = _selection(catalog)
    selection["version"] = True
    with pytest.raises(PhotorealAnimatedReviewPlanError, match="numeric v1"):
        build_animated_review_plan(execution, catalog, selection, animation_output_root=animation_root)
