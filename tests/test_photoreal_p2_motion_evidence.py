from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.photoreal_p2_animation_plan as p2_plan
import bodyrig.photoreal_p2_motion_evidence as motion
from bodyrig.photoreal_p2_motion_evidence import (
    PhotorealP2MotionEvidenceError,
    build_motion_evidence_handoff,
    build_motion_evidence_handoff_files,
    validate_motion_evidence_handoff,
    validate_private_motion_index,
)


def _digest(value: dict[str, object], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _source(
    *,
    key: str,
    group: str,
    path: str,
    sha: str,
    kind: str = "video",
    projection: str = "flat",
    stereo: str = "mono",
) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": group,
        "kind": kind,
        "resolved_path": path,
        "size_bytes": 123456,
        "sha256": sha * 64,
        "information_score": 100.0,
        "width": 3840,
        "height": 2160,
        "projection": projection,
        "stereo_layout": stereo,
    }


def _observation(*, key: str, group: str, split: str, sha: str) -> dict[str, object]:
    return {
        "source_key": key,
        "group_id": group,
        "split": split,
        "frame_sha256": sha * 64,
        "timestamp_seconds": 1.25,
        "eye": "mono",
        "view_bin": "front",
        "coverage": ["face-front", "full-body-front"],
    }


def _teacher_input() -> dict[str, object]:
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
        "training_sources": [
            _source(
                key="scene:train:E:/train.mp4",
                group="scene:train",
                path=r"\\stash\VR_E\train.mp4",
                sha="e",
            )
        ],
        "held_out_evaluation_sources": [
            _source(
                key="scene:eval:E:/eval.mp4",
                group="scene:eval",
                path=r"\\stash\VR_E\eval.mp4",
                sha="f",
            )
        ],
        "training_observations": [
            _observation(
                key="scene:train:E:/train.mp4",
                group="scene:train",
                split="train",
                sha="1",
            )
        ],
        "held_out_evaluation_observations": [
            _observation(
                key="scene:eval:E:/eval.mp4",
                group="scene:eval",
                split="evaluation",
                sha="2",
            )
        ],
        "held_out_view_coverage_required": ["face-front", "full-body-front"],
        "held_out_view_coverage_observed": ["face-front", "full-body-front"],
        "held_out_view_coverage_missing": [],
        "training_source_count": 1,
        "held_out_evaluation_source_count": 1,
        "training_observation_count": 1,
        "held_out_evaluation_observation_count": 1,
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


def _reseal_teacher(value: dict[str, object]) -> None:
    value.pop("teacher_input_sha256", None)
    value["teacher_input_sha256"] = _digest(value)


def _p2_plan(teacher_input_sha256: str) -> dict[str, object]:
    value: dict[str, object] = {
        "format": p2_plan.FORMAT,
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": teacher_input_sha256,
        "teacher_manifest_file_sha256": "3" * 64,
        "teacher_adapter": p2_plan.STATIC_TEACHER_ADAPTER,
        "teacher_adapter_revision": "4" * 64,
        "teacher_upstream_repository": p2_plan.PINNED_UPSTREAM_REPOSITORY,
        "teacher_upstream_commit": p2_plan.PINNED_UPSTREAM_COMMIT,
        "teacher_checkpoint": {
            "relative_path": p2_plan.EXPECTED_CHECKPOINT,
            "sha256": "5" * 64,
            "size_bytes": 123,
        },
        "p1_likeness_review_manifest_sha256": "6" * 64,
        "p1_likeness_review_sha256": "7" * 64,
        "animation_adapter": p2_plan.ADAPTER,
        "animation_contract": {
            "upstream_repository": p2_plan.PINNED_UPSTREAM_REPOSITORY,
            "upstream_commit": p2_plan.PINNED_UPSTREAM_COMMIT,
            "upstream_script": p2_plan.UPSTREAM_ANIMATION_SCRIPT,
            "test_epoch": p2_plan.EXPECTED_TEST_EPOCH,
            "motion_path_layout": {
                "reference_frames": "frames/<frame>.png",
                "camera_parameters": "cam_params/<frame>.json",
                "smplx_parameters": "smplx_optimized/smplx_params_smoothed/<frame>.json",
            },
            "required_smplx_fields": list(p2_plan.REQUIRED_SMPLX_FIELDS),
            "required_camera_fields": list(p2_plan.REQUIRED_CAMERA_FIELDS),
            "frame_id_contract": "integer filename stem shared across frames/camera/SMPL-X parameter files",
            "identity_shape_source": "accepted-static-teacher",
            "visual_identity_authority": "accepted-static-teacher",
            "rig_role": "motion-and-correspondence-only",
        },
        "required_motion_validation_criteria": list(
            p2_plan.REQUIRED_MOTION_VALIDATION_CRITERIA
        ),
        "source_motion_evidence_required": True,
        "held_out_motion_validation_required": True,
        "human_motion_acceptance_required": True,
        "p1_static_teacher_acceptance_authority": True,
        "p2_animation_build_authorized": True,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    value["p2_animation_plan_sha256"] = p2_plan._digest(
        value,
        omit="p2_animation_plan_sha256",
    )
    return value


def test_motion_handoff_preserves_train_eval_roles_and_hides_paths() -> None:
    teacher = _teacher_input()
    plan = _p2_plan(teacher["teacher_input_sha256"])

    handoff, private_index = build_motion_evidence_handoff(teacher, plan)

    assert handoff["motion_driver_candidate_count"] == 1
    assert handoff["held_out_motion_validation_candidate_count"] == 1
    assert handoff["motion_driver_candidates"][0]["split"] == "train"
    assert handoff["held_out_motion_validation_candidates"][0]["split"] == "evaluation"
    assert handoff["source_media_rehash_performed"] is False
    assert handoff["p2_motion_input_authorized"] is False
    assert handoff["p2_animation_execution_authorized"] is False
    assert handoff["p2_animated_teacher_acceptance_authority"] is False
    assert handoff["production_activation"] is False

    public_bytes = json.dumps(handoff, sort_keys=True)
    assert "E:/train.mp4" not in public_bytes
    assert "E:/eval.mp4" not in public_bytes
    assert "\\\\stash" not in public_bytes
    assert "source_key" not in public_bytes
    assert "resolved_path" not in public_bytes

    private_bytes = json.dumps(private_index, sort_keys=True)
    assert "E:/train.mp4" in private_bytes
    assert "E:/eval.mp4" in private_bytes
    assert "resolved_path" in private_bytes
    assert private_index["build_private"] is True
    assert private_index["source_media_rehash_performed"] is False


def test_motion_handoff_validator_rejects_resealed_private_path_leak() -> None:
    teacher = _teacher_input()
    plan = _p2_plan(teacher["teacher_input_sha256"])
    handoff, _private = build_motion_evidence_handoff(teacher, plan)
    handoff["motion_driver_candidates"][0]["resolved_path"] = r"\\stash\leak.mp4"
    handoff["p2_motion_evidence_handoff_sha256"] = motion._digest(
        handoff,
        omit="p2_motion_evidence_handoff_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionEvidenceError,
        match="leaks private source identity",
    ):
        validate_motion_evidence_handoff(handoff)


def test_private_motion_index_validator_rejects_resealed_public_binding_drift() -> None:
    teacher = _teacher_input()
    plan = _p2_plan(teacher["teacher_input_sha256"])
    handoff, private_index = build_motion_evidence_handoff(teacher, plan)
    private_index["entries"][0]["source_sha256"] = "9" * 64
    private_index["p2_motion_private_index_sha256"] = motion._digest(
        private_index,
        omit="p2_motion_private_index_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionEvidenceError,
        match="private/public P2 motion binding mismatch: source_sha256",
    ):
        validate_private_motion_index(private_index, handoff=handoff)


def test_motion_handoff_marks_spatial_video_for_exact_deprojection() -> None:
    teacher = _teacher_input()
    teacher["training_sources"][0]["projection"] = "vr180"
    teacher["training_sources"][0]["stereo_layout"] = "side-by-side"
    _reseal_teacher(teacher)
    plan = _p2_plan(teacher["teacher_input_sha256"])

    handoff, _private = build_motion_evidence_handoff(teacher, plan)

    assert (
        handoff["motion_driver_candidates"][0]["preparation_mode"]
        == "exact-authorized-deprojection-required"
    )


def test_motion_handoff_rejects_p2_teacher_input_provenance_drift() -> None:
    teacher = _teacher_input()
    plan = _p2_plan("9" * 64)

    with pytest.raises(
        PhotorealP2MotionEvidenceError,
        match="provenance mismatch: teacher_input_sha256",
    ):
        build_motion_evidence_handoff(teacher, plan)


def test_motion_handoff_rejects_resealed_p2_authority_escalation() -> None:
    teacher = _teacher_input()
    plan = _p2_plan(teacher["teacher_input_sha256"])
    plan["p2_animated_teacher_acceptance_authority"] = True
    plan["p2_animation_plan_sha256"] = p2_plan._digest(
        plan,
        omit="p2_animation_plan_sha256",
    )

    with pytest.raises(
        PhotorealP2MotionEvidenceError,
        match="P2 animation plan strict readback failed",
    ):
        build_motion_evidence_handoff(teacher, plan)


def test_motion_handoff_requires_video_in_both_original_splits() -> None:
    teacher = _teacher_input()
    teacher["held_out_evaluation_sources"][0]["kind"] = "image"
    _reseal_teacher(teacher)
    plan = _p2_plan(teacher["teacher_input_sha256"])

    with pytest.raises(
        PhotorealP2MotionEvidenceError,
        match="evaluation-split video",
    ):
        build_motion_evidence_handoff(teacher, plan)


def test_motion_handoff_file_reuse_is_exact_and_tamper_fails(tmp_path: Path) -> None:
    teacher = _teacher_input()
    plan = _p2_plan(teacher["teacher_input_sha256"])
    teacher_path = tmp_path / "teacher-input.json"
    plan_path = tmp_path / "p2-animation-plan.json"
    output = tmp_path / "motion-handoff"
    teacher_path.write_text(json.dumps(teacher, sort_keys=True) + "\n", encoding="utf-8")
    plan_path.write_text(json.dumps(plan, sort_keys=True) + "\n", encoding="utf-8")

    first = build_motion_evidence_handoff_files(
        teacher_path,
        plan_path,
        output,
    )
    second = build_motion_evidence_handoff_files(
        teacher_path,
        plan_path,
        output,
        reuse_existing=True,
    )
    assert first == second

    handoff_path = output / "p2-motion-evidence-handoff.json"
    tampered = json.loads(handoff_path.read_text(encoding="utf-8"))
    tampered["p2_motion_input_authorized"] = True
    handoff_path.write_text(json.dumps(tampered, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP2MotionEvidenceError,
        match="differs from canonical current state",
    ):
        build_motion_evidence_handoff_files(
            teacher_path,
            plan_path,
            output,
            reuse_existing=True,
        )
