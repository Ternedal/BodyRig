from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.photoreal_device_distillation_plan import CANDIDATE_REPRESENTATIONS, FIDELITY_DIMENSIONS
from bodyrig.photoreal_device_runtime_review_authority import (
    PhotorealDeviceRuntimeReviewAuthorityError,
    validate_device_runtime_review_plan,
)
from bodyrig.photoreal_device_runtime_review_plan import (
    PhotorealDeviceRuntimeReviewPlanError,
    build_device_runtime_review_plan,
)


def _digest(value: dict[str, object], omit: str) -> str:
    payload = {key: item for key, item in value.items() if key != omit}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


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


def _plan() -> dict[str, object]:
    profile = _profile()
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-device-distillation-plan",
        "version": 1,
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "a" * 64,
        "teacher_manifest_sha256": "b" * 64,
        "static_teacher_review_sha256": "c" * 64,
        "animation_plan_sha256": "d" * 64,
        "animation_execution_receipt_sha256": "e" * 64,
        "animated_teacher_review_sha256": "f" * 64,
        "target_profile": profile,
        "target_profile_sha256": _digest(profile, "target_profile_sha256"),
        "distillation_source_artifact_count": 1,
        "distillation_source_artifacts": [
            {"kind": "animated-review-media", "relative_path": "animation/motion.bin", "size_bytes": 10, "sha256": "1" * 64}
        ],
        "source_artifact_bytes_reverified": True,
        "candidate_student_representations": list(CANDIDATE_REPRESENTATIONS),
        "gaussian_splat_requires_explicit_target_support": True,
        "teacher_remains_visual_authority": True,
        "student_may_not_claim_fidelity_above_teacher": True,
        "required_fidelity_delta_dimensions": list(FIDELITY_DIMENSIONS),
        "required_fidelity_delta_dimension_count": len(FIDELITY_DIMENSIONS),
        "fidelity_delta_measurement_required": True,
        "human_runtime_visual_acceptance_required": True,
        "distillation_adapter_required": True,
        "distillation_adapter_selected": False,
        "p3_distillation_execution_authorized": True,
        "runtime_acceptance_authority": False,
        "production_activation": False,
    }
    value["device_distillation_plan_sha256"] = _digest(value, "device_distillation_plan_sha256")
    return value


def _execution(plan: dict[str, object], student_sha: str, student_size: int) -> dict[str, object]:
    measurements = [
        {
            "dimension": dimension,
            "metric": "test-delta",
            "value": round((index + 1) / 100.0, 6),
            "unit": "normalized-delta",
            "teacher_reference": "accepted-animated-teacher",
            "student_reference": "distilled-student",
        }
        for index, dimension in enumerate(FIDELITY_DIMENSIONS)
    ]
    value: dict[str, object] = {
        "format": "bodyrig-photoreal-device-distillation-execution-receipt",
        "version": 1,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "teacher_manifest_sha256": plan["teacher_manifest_sha256"],
        "static_teacher_review_sha256": plan["static_teacher_review_sha256"],
        "animation_plan_sha256": plan["animation_plan_sha256"],
        "animation_execution_receipt_sha256": plan["animation_execution_receipt_sha256"],
        "animated_teacher_review_sha256": plan["animated_teacher_review_sha256"],
        "device_distillation_plan_sha256": plan["device_distillation_plan_sha256"],
        "target_profile_sha256": plan["target_profile_sha256"],
        "adapter": "test-distiller",
        "adapter_revision": "rev-1",
        "student_representation": "skinned-mesh-neural-texture",
        "distillation_complete": True,
        "consumed_distillation_source_artifacts": [
            {"relative_path": "animation/motion.bin", "sha256": "1" * 64}
        ],
        "fidelity_delta_measurements": measurements,
        "student_artifacts": [
            {
                "kind": "student-runtime-package",
                "relative_path": "student/avatar.bin",
                "size_bytes": student_size,
                "sha256": student_sha,
            }
        ],
        "artifact_bytes_verified_by_core": True,
        "student_fidelity_claim_exceeds_teacher": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "production_activation": False,
    }
    value["device_distillation_execution_receipt_sha256"] = _digest(
        value, "device_distillation_execution_receipt_sha256"
    )
    return value


def _inputs(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], Path]:
    root = tmp_path / "student-output"
    artifact = root / "student" / "avatar.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"exact-distilled-student")
    (root / "distillation-manifest.json").write_text("{}\n", encoding="utf-8")
    plan = _plan()
    execution = _execution(plan, hashlib.sha256(artifact.read_bytes()).hexdigest(), artifact.stat().st_size)
    return plan, execution, root


def test_runtime_review_plan_is_ready_but_has_no_physical_or_acceptance_authority(tmp_path: Path) -> None:
    plan, execution, root = _inputs(tmp_path)
    result = build_device_runtime_review_plan(plan, execution, student_output_root=root)
    validated = validate_device_runtime_review_plan(result)
    assert validated["target_profile"]["target_model"] == "quest-2"
    assert validated["student_artifact_bytes_reverified"] is True
    assert validated["physical_device_evidence_required"] is True
    assert validated["physical_device_evidence_present"] is False
    assert validated["human_runtime_visual_acceptance_required"] is True
    assert validated["runtime_review_ready"] is True
    assert validated["runtime_acceptance_authority"] is False
    assert validated["production_activation"] is False


def test_runtime_review_plan_rejects_student_byte_drift(tmp_path: Path) -> None:
    plan, execution, root = _inputs(tmp_path)
    (root / "student" / "avatar.bin").write_bytes(b"changed-student")
    with pytest.raises(PhotorealDeviceRuntimeReviewPlanError, match="size drifted|bytes drifted"):
        build_device_runtime_review_plan(plan, execution, student_output_root=root)


def test_runtime_review_plan_rejects_undeclared_student_output_file(tmp_path: Path) -> None:
    plan, execution, root = _inputs(tmp_path)
    (root / "unexpected.bin").write_bytes(b"unexpected")
    with pytest.raises(PhotorealDeviceRuntimeReviewPlanError, match="artifact universe drifted"):
        build_device_runtime_review_plan(plan, execution, student_output_root=root)


def test_runtime_review_plan_rejects_distillation_lineage_substitution(tmp_path: Path) -> None:
    plan, execution, root = _inputs(tmp_path)
    execution["animated_teacher_review_sha256"] = "8" * 64
    execution["device_distillation_execution_receipt_sha256"] = _digest(
        execution, "device_distillation_execution_receipt_sha256"
    )
    with pytest.raises(PhotorealDeviceRuntimeReviewPlanError, match="lineage mismatch"):
        build_device_runtime_review_plan(plan, execution, student_output_root=root)


def test_readback_rejects_resealed_physical_evidence_claim(tmp_path: Path) -> None:
    plan, execution, root = _inputs(tmp_path)
    result = build_device_runtime_review_plan(plan, execution, student_output_root=root)
    result["physical_device_evidence_present"] = True
    result["device_runtime_review_plan_sha256"] = _digest(result, "device_runtime_review_plan_sha256")
    with pytest.raises(PhotorealDeviceRuntimeReviewAuthorityError, match="prematurely claims physical device evidence"):
        validate_device_runtime_review_plan(result)


def test_readback_rejects_resealed_runtime_acceptance_claim(tmp_path: Path) -> None:
    plan, execution, root = _inputs(tmp_path)
    result = build_device_runtime_review_plan(plan, execution, student_output_root=root)
    result["runtime_acceptance_authority"] = True
    result["device_runtime_review_plan_sha256"] = _digest(result, "device_runtime_review_plan_sha256")
    with pytest.raises(PhotorealDeviceRuntimeReviewAuthorityError, match="prematurely grants runtime acceptance"):
        validate_device_runtime_review_plan(result)


def test_reserved_distillation_manifest_is_not_treated_as_student_artifact(tmp_path: Path) -> None:
    plan, execution, root = _inputs(tmp_path)
    result = build_device_runtime_review_plan(plan, execution, student_output_root=root)
    assert result["student_artifact_count"] == 1
    assert result["student_artifacts"][0]["relative_path"] == "student/avatar.bin"
