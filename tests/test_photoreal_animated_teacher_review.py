from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_animated_review_plan import MOTION_REVIEW_DIMENSIONS
from bodyrig.photoreal_animated_teacher_review import (
    CHECKS,
    PhotorealAnimatedTeacherReviewError,
    finalize_animated_teacher_review,
)
from bodyrig.photoreal_animated_teacher_review_authority import (
    PhotorealAnimatedTeacherReviewAuthorityError,
    require_p3_device_distillation_authority,
    validate_animated_teacher_review,
)
from bodyrig.photoreal_motion_reference_materializer import ADAPTER as MOTION_ADAPTER, SAMPLE_FPS


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _window_id(source_key: str, eye: str, start: float, end: float) -> str:
    return hashlib.sha256(
        json.dumps(
            {"source_key": source_key, "eye": eye, "window_start_seconds": start, "window_end_seconds": end},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _observation_id(source_key: str, frame_sha: str, timestamp: float, eye: str) -> str:
    return hashlib.sha256(
        json.dumps(
            {"source_key": source_key, "frame_sha256": frame_sha, "timestamp_seconds": timestamp, "eye": eye},
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _execution(animation_sha: str, animation_size: int) -> dict[str, object]:
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-animation-execution-receipt",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "teacher_manifest_sha256": "b" * 64,
        "static_teacher_review_sha256": "c" * 64,
        "animation_plan_sha256": "d" * 64,
        "adapter": "test-animation-adapter",
        "adapter_revision": "rev-1",
        "representation": "test-representation",
        "animation_complete": True,
        "consumed_teacher_artifacts": [{"relative_path": "teacher.bin", "sha256": "e" * 64}],
        "implemented_validation_dimensions": [
            "body_pose_smplx_correspondence",
            "face_expression_control",
            *MOTION_REVIEW_DIMENSIONS,
        ],
        "animation_artifacts": [
            {
                "kind": "animated-review-media",
                "relative_path": "animation/motion.bin",
                "size_bytes": animation_size,
                "sha256": animation_sha,
            }
        ],
        "artifact_bytes_verified_by_core": True,
        "animated_teacher_acceptance_authority": False,
        "human_animated_visual_acceptance_required": True,
        "p3_device_distillation_authorized": False,
        "production_activation": False,
    }
    value["animation_execution_receipt_sha256"] = _digest(value, "animation_execution_receipt_sha256")
    return value


def _plan(execution: dict[str, object]) -> tuple[dict[str, object], str, str]:
    source_key = "scene:eval:E:/held-out.mp4"
    eye = "mono"
    timestamp = 12.0
    start = 11.5
    end = 12.5
    frame_sha = "4" * 64
    observation_id = _observation_id(source_key, frame_sha, timestamp, eye)
    selections = []
    for dimension in MOTION_REVIEW_DIMENSIONS:
        selections.append(
            {
                "dimension": dimension,
                "animation_artifact_kind": "animated-review-media",
                "animation_artifact_relative_path": "animation/motion.bin",
                "animation_artifact_size_bytes": execution["animation_artifacts"][0]["size_bytes"],
                "animation_artifact_sha256": execution["animation_artifacts"][0]["sha256"],
                "reference_observation_id": observation_id,
                "reference_source_key": source_key,
                "reference_source_group_id": "eval-group",
                "reference_source_resolved_path": r"\\stash\VR_E\held-out.mp4",
                "reference_source_sha256": "3" * 64,
                "reference_source_projection": "flat",
                "reference_source_stereo_layout": "mono",
                "reference_timestamp_seconds": timestamp,
                "reference_eye": eye,
                "reference_view_bin": "front",
                "reference_frame_sha256": frame_sha,
                "window_before_seconds": 0.5,
                "window_after_seconds": 0.5,
                "window_start_seconds": start,
                "window_end_seconds": end,
                "reference_motion_bytes_materialized": False,
            }
        )
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-animated-review-plan",
        "version": 1,
        "performer_id": execution["performer_id"],
        "selected_epoch_id": execution["selected_epoch_id"],
        "teacher_input_sha256": execution["teacher_input_sha256"],
        "teacher_manifest_sha256": execution["teacher_manifest_sha256"],
        "static_teacher_review_sha256": execution["static_teacher_review_sha256"],
        "animation_plan_sha256": execution["animation_plan_sha256"],
        "animation_execution_receipt_sha256": execution["animation_execution_receipt_sha256"],
        "held_out_reference_catalog_sha256": "f" * 64,
        "reviewer": "selection-operator",
        "operator_supplied": True,
        "motion_review_dimensions": list(MOTION_REVIEW_DIMENSIONS),
        "selection_count": len(MOTION_REVIEW_DIMENSIONS),
        "selections": selections,
        "animation_artifact_bytes_reverified": True,
        "held_out_evaluation_only": True,
        "held_out_motion_reference_selection_complete": True,
        "motion_reference_materialization_required": True,
        "reference_motion_bytes_materialized": False,
        "human_animated_visual_acceptance_required": True,
        "animated_teacher_acceptance_authority": False,
        "p3_device_distillation_authorized": False,
        "source_paths_build_private": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["animated_review_plan_sha256"] = _digest(value, "animated_review_plan_sha256")
    return value, observation_id, _window_id(source_key, eye, start, end)


def _motion_receipt(tmp_path: Path, plan: dict[str, object], observation_id: str, window_id: str) -> tuple[dict[str, object], Path]:
    motion_root = tmp_path / "motion-output"
    frame_root = motion_root / "motion" / window_id
    frame_root.mkdir(parents=True)
    start = 11.5
    end = 12.5
    frames = []
    count = int((end - start) * SAMPLE_FPS) + 1
    for index in range(count):
        path = frame_root / f"{index:04d}.png"
        path.write_bytes(f"motion-frame-{index}".encode("ascii"))
        frames.append(
            {
                "index": index,
                "requested_timestamp_seconds": round(min(end, start + index / SAMPLE_FPS), 6),
                "decoded_frame_sha256": format((index % 15) + 1, "x") * 64,
                "png_relative_path": f"motion/{window_id}/{index:04d}.png",
                "png_size_bytes": path.stat().st_size,
                "png_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    canonical_dimensions = sorted(MOTION_REVIEW_DIMENSIONS)
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-motion-reference-materialization-receipt",
        "version": 1,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "animation_execution_receipt_sha256": plan["animation_execution_receipt_sha256"],
        "held_out_reference_catalog_sha256": plan["held_out_reference_catalog_sha256"],
        "animated_review_plan_sha256": plan["animated_review_plan_sha256"],
        "adapter": MOTION_ADAPTER,
        "revision": "9" * 64,
        "sample_fps": SAMPLE_FPS,
        "source_count": 1,
        "window_count": 1,
        "materialized_windows": [
            {
                "window_id": window_id,
                "source_key": "scene:eval:E:/held-out.mp4",
                "eye": "mono",
                "dimensions": canonical_dimensions,
                "window_start_seconds": start,
                "window_end_seconds": end,
                "sample_fps": SAMPLE_FPS,
                "anchors": [
                    {
                        "observation_id": observation_id,
                        "timestamp_seconds": 12.0,
                        "expected_frame_sha256": "4" * 64,
                        "observed_frame_sha256": "4" * 64,
                        "dimensions": canonical_dimensions,
                        "frame_hash_verified": True,
                    }
                ],
                "source_hash_verified": True,
                "all_anchor_hashes_verified": True,
                "frame_count": count,
                "frames": frames,
            }
        ],
        "all_source_hashes_verified": True,
        "all_anchor_hashes_verified": True,
        "artifact_bytes_verified_by_core": True,
        "decode_semantics": "opencv-bgr-array-v1",
        "frame_hash_semantics": "sha256(shape-ascii-newline+contiguous-bgr-bytes)",
        "teacher_process_disclosure": False,
        "reference_motion_bytes_materialized": True,
        "human_animated_visual_acceptance_required": True,
        "animated_teacher_acceptance_authority": False,
        "p3_device_distillation_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    value["motion_materialization_receipt_sha256"] = _digest(value, "motion_materialization_receipt_sha256")
    return value, motion_root


def _human(outcome: str = "pass") -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-animated-teacher-human-review-input",
        "version": 1,
        "reviewer": "operator",
        "operator_supplied": True,
        "dimension_reviews": [{"dimension": item, "outcome": outcome} for item in MOTION_REVIEW_DIMENSIONS],
        "checklist": {key: outcome for key in sorted(CHECKS)},
        "overall_decision": outcome,
        "quality_note": "Reviewed exact animated teacher bytes against exact held-out motion sequences.",
    }


def _inputs(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], dict[str, object], Path, Path]:
    animation_root = tmp_path / "animation-output"
    artifact = animation_root / "animation" / "motion.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"exact-animation-output")
    execution = _execution(hashlib.sha256(artifact.read_bytes()).hexdigest(), artifact.stat().st_size)
    plan, observation_id, window_id = _plan(execution)
    motion, motion_root = _motion_receipt(tmp_path, plan, observation_id, window_id)
    return execution, plan, motion, animation_root, motion_root


def test_human_animated_pass_authorizes_p3_but_not_production(tmp_path: Path) -> None:
    execution, plan, motion, animation_root, motion_root = _inputs(tmp_path)
    result = finalize_animated_teacher_review(
        execution, plan, motion, _human("pass"),
        animation_output_root=animation_root,
        motion_output_root=motion_root,
    )
    validated = validate_animated_teacher_review(result)
    assert validated["human_animated_review_pass"] is True
    assert validated["animated_teacher_acceptance_authority"] is True
    assert validated["p3_device_distillation_authorized"] is True
    assert validated["production_activation"] is False
    assert require_p3_device_distillation_authority(validated)["p3_device_distillation_authorized"] is True


def test_human_animated_fail_is_valid_persistent_rejection(tmp_path: Path) -> None:
    execution, plan, motion, animation_root, motion_root = _inputs(tmp_path)
    result = finalize_animated_teacher_review(
        execution, plan, motion, _human("fail"),
        animation_output_root=animation_root,
        motion_output_root=motion_root,
    )
    validated = validate_animated_teacher_review(result)
    assert validated["human_animated_review_pass"] is False
    assert validated["animated_teacher_acceptance_authority"] is False
    assert validated["p3_device_distillation_authorized"] is False
    with pytest.raises(PhotorealAnimatedTeacherReviewAuthorityError, match="requires an exact human-passed"):
        require_p3_device_distillation_authority(validated)


def test_human_animated_review_rejects_contradictory_overall_pass(tmp_path: Path) -> None:
    execution, plan, motion, animation_root, motion_root = _inputs(tmp_path)
    human = _human("pass")
    human["checklist"]["temporal_stability"] = "fail"
    with pytest.raises(PhotorealAnimatedTeacherReviewError, match="contradicts detailed outcomes"):
        finalize_animated_teacher_review(
            execution, plan, motion, human,
            animation_output_root=animation_root,
            motion_output_root=motion_root,
        )


def test_human_animated_review_rejects_animation_byte_drift(tmp_path: Path) -> None:
    execution, plan, motion, animation_root, motion_root = _inputs(tmp_path)
    (animation_root / "animation" / "motion.bin").write_bytes(b"changed-animation-output")
    with pytest.raises(PhotorealAnimatedTeacherReviewError, match="bytes drifted"):
        finalize_animated_teacher_review(
            execution, plan, motion, _human(),
            animation_output_root=animation_root,
            motion_output_root=motion_root,
        )


def test_human_animated_review_rejects_motion_reference_byte_drift(tmp_path: Path) -> None:
    execution, plan, motion, animation_root, motion_root = _inputs(tmp_path)
    first = motion["materialized_windows"][0]["frames"][0]
    (motion_root / first["png_relative_path"]).write_bytes(b"changed-motion-reference")
    with pytest.raises(PhotorealAnimatedTeacherReviewError, match="PNG bytes drifted"):
        finalize_animated_teacher_review(
            execution, plan, motion, _human(),
            animation_output_root=animation_root,
            motion_output_root=motion_root,
        )


def test_human_animated_review_rejects_lineage_substitution(tmp_path: Path) -> None:
    execution, plan, motion, animation_root, motion_root = _inputs(tmp_path)
    plan["teacher_manifest_sha256"] = "8" * 64
    plan["animated_review_plan_sha256"] = _digest(plan, "animated_review_plan_sha256")
    with pytest.raises(PhotorealAnimatedTeacherReviewError, match="teacher manifest lineage mismatch"):
        finalize_animated_teacher_review(
            execution, plan, motion, _human(),
            animation_output_root=animation_root,
            motion_output_root=motion_root,
        )


def test_animated_review_readback_rejects_resealed_authority_mismatch(tmp_path: Path) -> None:
    execution, plan, motion, animation_root, motion_root = _inputs(tmp_path)
    result = finalize_animated_teacher_review(
        execution, plan, motion, _human("pass"),
        animation_output_root=animation_root,
        motion_output_root=motion_root,
    )
    result["p3_device_distillation_authorized"] = False
    result["animated_teacher_review_sha256"] = _digest(result, "animated_teacher_review_sha256")
    with pytest.raises(PhotorealAnimatedTeacherReviewAuthorityError, match="authority mismatch"):
        validate_animated_teacher_review(result)
