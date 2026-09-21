from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import bodyrig.photoreal_p3_device_runtime_review_plan as runtime
from bodyrig.photoreal_p3_device_runtime_review_plan import (
    PhotorealP3DeviceRuntimeReviewPlanError,
    build_device_runtime_review_plan,
    validate_device_runtime_review_plan,
)
from bodyrig.photoreal_p3_device_distillation_plan import (
    FIDELITY_DELTA_DIMENSIONS,
)
from bodyrig.photoreal_p3_device_distillation_runner import (
    REQUIRED_STUDENT_COMPONENTS,
)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _profile() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-device-target-profile",
        "version": 1,
        "operator_supplied": True,
        "target_family": "meta-quest",
        "target_model": "quest-2",
        "target_runtime": "standalone",
        "target_refresh_hz": 72.0,
        "max_frame_time_ms": 13.888889,
        "stereo_rendering_required": True,
        "vr_safe_frame_pacing_required": True,
        "teacher_quality_ceiling_preserved": True,
        "fidelity_delta_reporting_required": True,
        "production_activation": False,
    }


def _inputs(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], Path]:
    output = tmp_path / "execution" / "output"
    artifact = output / "student" / "avatar.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"exact-student-runtime")
    (output / "distillation-manifest.json").write_text("{}\n", encoding="utf-8")

    profile = _profile()
    plan: dict[str, object] = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "p2_animated_human_review_sha256": "4" * 64,
        "p3_device_distillation_plan_sha256": "5" * 64,
        "target_profile": profile,
        "target_profile_sha256": runtime._digest(profile),
    }
    measurements = [
        {
            "dimension": dimension,
            "metric": "normalized-delta",
            "value": round((index + 1) / 100.0, 6),
            "unit": "delta",
            "teacher_reference": "accepted-teacher",
            "student_reference": "student-runtime",
        }
        for index, dimension in enumerate(FIDELITY_DELTA_DIMENSIONS)
    ]
    execution: dict[str, object] = {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "p2_animated_human_review_sha256": "4" * 64,
        "p3_device_distillation_plan_sha256": "5" * 64,
        "p3_device_distillation_request_sha256": "6" * 64,
        "p3_device_distillation_execution_receipt_sha256": "7" * 64,
        "target_profile_sha256": plan["target_profile_sha256"],
        "target_model": "quest-2",
        "adapter": "test-distiller",
        "adapter_revision": "a" * 64,
        "student_representation": "skinned-mesh-neural-texture",
        "student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "distillation_complete": True,
        "artifact_bytes_verified_by_core": True,
        "staged_teacher_only": True,
        "student_fidelity_claim_exceeds_teacher": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
        "fidelity_delta_measurements": measurements,
        "student_artifacts": [
            {
                "kind": "student-runtime-package",
                "relative_path": "student/avatar.bin",
                "size_bytes": artifact.stat().st_size,
                "sha256": _sha(artifact.read_bytes()),
            }
        ],
    }
    return plan, execution, output


def _trust(
    monkeypatch: pytest.MonkeyPatch,
    plan: dict[str, object],
    execution: dict[str, object],
) -> None:
    monkeypatch.setattr(
        runtime,
        "validate_p3_device_distillation_plan",
        lambda value: plan,
    )
    monkeypatch.setattr(
        runtime,
        "validate_execution_receipt",
        lambda value: execution,
    )


def test_runtime_review_plan_reverifies_student_and_stays_pre_physical(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    _trust(monkeypatch, plan, execution)

    result = build_device_runtime_review_plan(
        plan,
        execution,
        student_output_root=output,
    )

    assert result["target_device_model"] == "quest-2"
    assert result["executed_adapter"] == "test-distiller"
    assert result["executed_adapter_revision"] == "a" * 64
    assert result["student_artifact_bytes_reverified"] is True
    assert result["student_components"] == list(REQUIRED_STUDENT_COMPONENTS)
    assert result["fidelity_delta_dimension_count"] == len(
        FIDELITY_DELTA_DIMENSIONS
    )
    assert result["physical_device_installation_required"] is True
    assert result["physical_device_evidence_required"] is True
    assert result["physical_device_evidence_present"] is False
    assert result["runtime_review_ready"] is True
    assert result["runtime_acceptance_authority"] is False
    assert result["photoreal_acceptance_authority"] is False
    assert result["production_activation"] is False


def test_runtime_review_plan_rejects_student_byte_drift(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    _trust(monkeypatch, plan, execution)
    (output / "student" / "avatar.bin").write_bytes(b"changed")

    with pytest.raises(
        PhotorealP3DeviceRuntimeReviewPlanError,
        match="size/path drifted|bytes drifted",
    ):
        build_device_runtime_review_plan(
            plan,
            execution,
            student_output_root=output,
        )


def test_runtime_review_plan_rejects_undeclared_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    _trust(monkeypatch, plan, execution)
    (output / "unexpected.bin").write_bytes(b"unexpected")

    with pytest.raises(
        PhotorealP3DeviceRuntimeReviewPlanError,
        match="artifact universe drifted",
    ):
        build_device_runtime_review_plan(
            plan,
            execution,
            student_output_root=output,
        )


def test_runtime_review_plan_rejects_nested_manifest_named_output(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    _trust(monkeypatch, plan, execution)
    nested = output / "student" / "distillation-manifest.json"
    nested.write_text("{}\n", encoding="utf-8")

    with pytest.raises(
        PhotorealP3DeviceRuntimeReviewPlanError,
        match="artifact universe drifted",
    ):
        build_device_runtime_review_plan(
            plan,
            execution,
            student_output_root=output,
        )


def test_runtime_review_plan_rejects_lineage_substitution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    execution["p2_animated_human_review_sha256"] = "9" * 64
    _trust(monkeypatch, plan, execution)

    with pytest.raises(
        PhotorealP3DeviceRuntimeReviewPlanError,
        match="lineage mismatch",
    ):
        build_device_runtime_review_plan(
            plan,
            execution,
            student_output_root=output,
        )


def test_runtime_review_plan_requires_eye_and_hair_components(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    execution["student_components"] = ["specialized-eye-component"]
    _trust(monkeypatch, plan, execution)

    with pytest.raises(
        PhotorealP3DeviceRuntimeReviewPlanError,
        match="required eye/hair components",
    ):
        build_device_runtime_review_plan(
            plan,
            execution,
            student_output_root=output,
        )


def test_readback_rejects_resealed_physical_evidence_claim(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    _trust(monkeypatch, plan, execution)
    result = build_device_runtime_review_plan(
        plan,
        execution,
        student_output_root=output,
    )
    result["physical_device_evidence_present"] = True
    result["p3_device_runtime_review_plan_sha256"] = runtime._digest(
        result,
        omit="p3_device_runtime_review_plan_sha256",
    )

    with pytest.raises(
        PhotorealP3DeviceRuntimeReviewPlanError,
        match="physical_device_evidence_present",
    ):
        validate_device_runtime_review_plan(result)


def test_readback_rejects_resealed_runtime_acceptance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    _trust(monkeypatch, plan, execution)
    result = build_device_runtime_review_plan(
        plan,
        execution,
        student_output_root=output,
    )
    result["runtime_acceptance_authority"] = True
    result["p3_device_runtime_review_plan_sha256"] = runtime._digest(
        result,
        omit="p3_device_runtime_review_plan_sha256",
    )

    with pytest.raises(
        PhotorealP3DeviceRuntimeReviewPlanError,
        match="runtime_acceptance_authority",
    ):
        validate_device_runtime_review_plan(result)


def test_readback_rejects_boolean_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    _trust(monkeypatch, plan, execution)
    result = build_device_runtime_review_plan(
        plan,
        execution,
        student_output_root=output,
    )
    result["version"] = True
    result["p3_device_runtime_review_plan_sha256"] = runtime._digest(
        result,
        omit="p3_device_runtime_review_plan_sha256",
    )

    with pytest.raises(
        PhotorealP3DeviceRuntimeReviewPlanError,
        match="format/version mismatch",
    ):
        validate_device_runtime_review_plan(result)

def test_runtime_review_plan_rejects_executed_target_substitution(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    execution["target_model"] = "quest-3"
    _trust(monkeypatch, plan, execution)

    with pytest.raises(
        PhotorealP3DeviceRuntimeReviewPlanError,
        match="executed target model differs",
    ):
        build_device_runtime_review_plan(
            plan,
            execution,
            student_output_root=output,
        )


def test_runtime_review_plan_rejects_non_sha_adapter_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plan, execution, output = _inputs(tmp_path)
    execution["adapter_revision"] = "rev-1"
    _trust(monkeypatch, plan, execution)

    with pytest.raises(
        PhotorealP3DeviceRuntimeReviewPlanError,
        match="executed adapter revision",
    ):
        build_device_runtime_review_plan(
            plan,
            execution,
            student_output_root=output,
        )

