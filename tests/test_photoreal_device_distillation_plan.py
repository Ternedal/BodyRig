from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_animated_review_plan import MOTION_REVIEW_DIMENSIONS
from bodyrig.photoreal_animated_teacher_review import CHECKS
from bodyrig.photoreal_animation_plan import ANIMATION_REQUIREMENTS
from bodyrig.photoreal_device_distillation_authority import (
    PhotorealDeviceDistillationAuthorityError,
    require_distillation_execution_authority,
    validate_device_distillation_plan,
)
from bodyrig.photoreal_device_distillation_plan import (
    CANDIDATE_REPRESENTATIONS,
    FIDELITY_DIMENSIONS,
    PhotorealDeviceDistillationPlanError,
    build_device_distillation_plan,
)


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _execution(artifact_sha: str, artifact_size: int) -> dict[str, object]:
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
        "representation": "teacher-animation-representation",
        "animation_complete": True,
        "consumed_teacher_artifacts": [{"relative_path": "teacher.bin", "sha256": "e" * 64}],
        "implemented_validation_dimensions": list(ANIMATION_REQUIREMENTS),
        "animation_artifacts": [
            {
                "kind": "animated-review-media",
                "relative_path": "animation/motion.bin",
                "size_bytes": artifact_size,
                "sha256": artifact_sha,
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


def _review(execution: dict[str, object], *, passed: bool = True) -> dict[str, object]:
    outcome = "pass" if passed else "fail"
    reviews = []
    for dimension in MOTION_REVIEW_DIMENSIONS:
        reviews.append(
            {
                "dimension": dimension,
                "animation_artifact_relative_path": "animation/motion.bin",
                "animation_artifact_sha256": execution["animation_artifacts"][0]["sha256"],
                "motion_window_id": "1" * 64,
                "reference_observation_id": "2" * 64,
                "reference_frame_sha256": "3" * 64,
                "materialized_reference_frame_count": 25,
                "human_outcome": outcome,
            }
        )
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-animated-teacher-human-review",
        "version": 1,
        "performer_id": execution["performer_id"],
        "selected_epoch_id": execution["selected_epoch_id"],
        "teacher_input_sha256": execution["teacher_input_sha256"],
        "teacher_manifest_sha256": execution["teacher_manifest_sha256"],
        "static_teacher_review_sha256": execution["static_teacher_review_sha256"],
        "animation_plan_sha256": execution["animation_plan_sha256"],
        "animation_execution_receipt_sha256": execution["animation_execution_receipt_sha256"],
        "animated_review_plan_sha256": "4" * 64,
        "motion_materialization_receipt_sha256": "5" * 64,
        "reviewer": "operator",
        "reviewed_utc": "2026-09-15T08:00:00+00:00",
        "operator_supplied": True,
        "dimension_review_count": len(MOTION_REVIEW_DIMENSIONS),
        "dimension_reviews": reviews,
        "checklist": {key: outcome for key in sorted(CHECKS)},
        "quality_note": "Exact animated teacher reviewed against exact held-out motion evidence.",
        "animation_artifact_bytes_reverified_at_review": True,
        "motion_reference_bytes_reverified_at_review": True,
        "human_animated_review_complete": True,
        "human_animated_review_outcome": outcome,
        "human_animated_review_pass": passed,
        "animated_teacher_photoreal_accepted": passed,
        "animated_teacher_acceptance_authority": passed,
        "p3_device_distillation_authorized": passed,
        "production_activation": False,
    }
    value["animated_teacher_review_sha256"] = _digest(value, "animated_teacher_review_sha256")
    return value


def _profile() -> dict[str, object]:
    refresh = 72.0
    return {
        "format": "bodyrig-photoreal-device-target-profile",
        "version": 1,
        "operator_supplied": True,
        "target_family": "meta-quest",
        "target_model": "quest-2",
        "target_runtime": "standalone",
        "target_refresh_hz": refresh,
        "max_frame_time_ms": round(1000.0 / refresh, 6),
        "stereo_rendering_required": True,
        "vr_safe_frame_pacing_required": True,
        "teacher_quality_ceiling_preserved": True,
        "fidelity_delta_reporting_required": True,
        "production_activation": False,
    }


def _inputs(tmp_path: Path, *, passed: bool = True) -> tuple[dict[str, object], dict[str, object], dict[str, object], Path]:
    root = tmp_path / "animation-output"
    artifact = root / "animation" / "motion.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"exact-accepted-animation-teacher")
    # The raw adapter manifest is reserved metadata, not a distillation source artifact.
    (root / "animation-manifest.json").write_text("{}\n", encoding="utf-8")
    execution = _execution(hashlib.sha256(artifact.read_bytes()).hexdigest(), artifact.stat().st_size)
    return _review(execution, passed=passed), execution, _profile(), root


def test_p2_human_pass_builds_quest2_p3_plan_without_runtime_acceptance(tmp_path: Path) -> None:
    review, execution, profile, root = _inputs(tmp_path)
    plan = build_device_distillation_plan(review, execution, profile, animation_output_root=root)
    validated = validate_device_distillation_plan(plan)
    assert validated["target_profile"]["target_model"] == "quest-2"
    assert validated["source_artifact_bytes_reverified"] is True
    assert validated["candidate_student_representations"] == list(CANDIDATE_REPRESENTATIONS)
    assert validated["required_fidelity_delta_dimensions"] == list(FIDELITY_DIMENSIONS)
    assert validated["student_may_not_claim_fidelity_above_teacher"] is True
    assert validated["p3_distillation_execution_authorized"] is True
    assert validated["runtime_acceptance_authority"] is False
    assert validated["production_activation"] is False
    assert require_distillation_execution_authority(validated)["p3_distillation_execution_authorized"] is True


def test_p2_human_fail_cannot_open_p3(tmp_path: Path) -> None:
    review, execution, profile, root = _inputs(tmp_path, passed=False)
    with pytest.raises(PhotorealDeviceDistillationPlanError, match="requires an exact human-passed"):
        build_device_distillation_plan(review, execution, profile, animation_output_root=root)


def test_target_profile_requires_exact_refresh_derived_frame_budget(tmp_path: Path) -> None:
    review, execution, profile, root = _inputs(tmp_path)
    profile["max_frame_time_ms"] = 10.0
    with pytest.raises(PhotorealDeviceDistillationPlanError, match="1000/target_refresh_hz"):
        build_device_distillation_plan(review, execution, profile, animation_output_root=root)


def test_p3_plan_rejects_distillation_source_byte_drift(tmp_path: Path) -> None:
    review, execution, profile, root = _inputs(tmp_path)
    (root / "animation" / "motion.bin").write_bytes(b"changed-after-p2-human-pass")
    with pytest.raises(PhotorealDeviceDistillationPlanError, match="size drifted|bytes drifted"):
        build_device_distillation_plan(review, execution, profile, animation_output_root=root)


def test_p3_plan_rejects_undeclared_animation_output_file(tmp_path: Path) -> None:
    review, execution, profile, root = _inputs(tmp_path)
    (root / "unexpected.bin").write_bytes(b"undeclared")
    with pytest.raises(PhotorealDeviceDistillationPlanError, match="artifact universe drifted"):
        build_device_distillation_plan(review, execution, profile, animation_output_root=root)


def test_raw_animation_manifest_is_reserved_and_does_not_break_source_universe(tmp_path: Path) -> None:
    review, execution, profile, root = _inputs(tmp_path)
    plan = build_device_distillation_plan(review, execution, profile, animation_output_root=root)
    assert plan["distillation_source_artifact_count"] == 1
    assert plan["distillation_source_artifacts"][0]["relative_path"] == "animation/motion.bin"


def test_readback_rejects_resealed_fidelity_policy_tamper(tmp_path: Path) -> None:
    review, execution, profile, root = _inputs(tmp_path)
    plan = build_device_distillation_plan(review, execution, profile, animation_output_root=root)
    plan["student_may_not_claim_fidelity_above_teacher"] = False
    plan["device_distillation_plan_sha256"] = _digest(plan, "device_distillation_plan_sha256")
    with pytest.raises(PhotorealDeviceDistillationAuthorityError, match="requirement missing"):
        validate_device_distillation_plan(plan)


def test_readback_rejects_resealed_representation_universe_tamper(tmp_path: Path) -> None:
    review, execution, profile, root = _inputs(tmp_path)
    plan = build_device_distillation_plan(review, execution, profile, animation_output_root=root)
    plan["candidate_student_representations"] = ["gaussian-splat-optional"]
    plan["device_distillation_plan_sha256"] = _digest(plan, "device_distillation_plan_sha256")
    with pytest.raises(PhotorealDeviceDistillationAuthorityError, match="candidate universe"):
        validate_device_distillation_plan(plan)


def test_profile_rejects_boolean_v1() -> None:
    profile = _profile()
    profile["version"] = True
    from bodyrig.photoreal_device_distillation_plan import validate_device_target_profile

    with pytest.raises(PhotorealDeviceDistillationPlanError, match="numeric v1"):
        validate_device_target_profile(profile)
