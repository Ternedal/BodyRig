from __future__ import annotations

import copy

import pytest

import bodyrig.photoreal_p3_physical_runtime_review as physical
from bodyrig.photoreal_p3_device_distillation_plan import (
    FIDELITY_DELTA_DIMENSIONS,
)
from bodyrig.photoreal_p3_device_distillation_runner import (
    REQUIRED_STUDENT_COMPONENTS,
)
from bodyrig.photoreal_p3_physical_runtime_review import (
    PhotorealP3PhysicalRuntimeReviewError,
    PERFORMANCE_CHECKS,
    record_physical_runtime_review,
    validate_physical_runtime_review_evidence,
    validate_physical_runtime_review_receipt,
)


def _plan() -> dict[str, object]:
    return {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "teacher_input_sha256": "1" * 64,
        "p2_animation_plan_sha256": "2" * 64,
        "p2_exavatar_animation_execution_input_sha256": "3" * 64,
        "p2_animated_human_review_sha256": "4" * 64,
        "p3_device_distillation_plan_sha256": "5" * 64,
        "p3_device_distillation_execution_receipt_sha256": "6" * 64,
        "p3_device_runtime_review_plan_sha256": "7" * 64,
        "target_profile_sha256": "8" * 64,
        "target_profile": {
            "target_refresh_hz": 72.0,
            "max_frame_time_ms": 13.888889,
        },
        "target_device_family": "meta-quest",
        "target_device_model": "quest-2",
        "student_representation": "skinned-mesh-neural-texture",
        "student_components": list(REQUIRED_STUDENT_COMPONENTS),
        "student_artifacts": [
            {
                "kind": "student-runtime-package",
                "relative_path": "student/avatar.bin",
                "size_bytes": 123,
                "sha256": "9" * 64,
            }
        ],
    }


def _evidence(*, visual: str = "pass") -> dict[str, object]:
    return {
        "format": physical.EVIDENCE_FORMAT,
        "version": 1,
        "operator_supplied": True,
        "runtime_review_plan_sha256": "7" * 64,
        "target_device_family": "meta-quest",
        "target_device_model": "quest-2",
        "physical_device_observed": True,
        "installed_student_artifacts": [
            {
                "relative_path": "student/avatar.bin",
                "sha256": "9" * 64,
            }
        ],
        "observed_refresh_hz": 72.0,
        "p95_frame_time_ms": 12.5,
        "stereo_rendering_observed": True,
        "vr_safe_frame_pacing_observed": True,
        "installed_student_hashes_verified_on_device": True,
        "visual_results": [
            {"criterion": item, "decision": visual}
            for item in FIDELITY_DELTA_DIMENSIONS
        ],
        "reviewed_by": "operator",
        "review_notes": "Physical Quest review completed.",
        "confirm_physical_device_review_complete": True,
    }


def _trust(
    monkeypatch: pytest.MonkeyPatch,
    plan: dict[str, object],
) -> None:
    monkeypatch.setattr(
        physical,
        "validate_device_runtime_review_plan",
        lambda value: plan,
    )


def test_exact_physical_all_pass_grants_runtime_and_photoreal_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)

    receipt = record_physical_runtime_review(plan, _evidence())

    assert receipt["runtime_review_status"] == "pass"
    assert receipt["physical_device_evidence_present"] is True
    assert receipt["physical_device_review_complete"] is True
    assert receipt["runtime_acceptance_authority"] is True
    assert receipt["photoreal_acceptance_authority"] is True
    assert receipt["production_activation"] is False
    assert [item["criterion"] for item in receipt["performance_results"]] == list(
        PERFORMANCE_CHECKS
    )


def test_visual_fail_blocks_runtime_and_photoreal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    evidence = _evidence()
    evidence["visual_results"][0]["decision"] = "fail"

    receipt = record_physical_runtime_review(plan, evidence)

    assert receipt["runtime_review_status"] == "fail"
    assert receipt["runtime_acceptance_authority"] is False
    assert receipt["photoreal_acceptance_authority"] is False
    assert receipt["production_activation"] is False


def test_p95_frame_budget_fail_blocks_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    evidence = _evidence()
    evidence["p95_frame_time_ms"] = 14.0

    receipt = record_physical_runtime_review(plan, evidence)

    assert receipt["runtime_review_status"] == "fail"
    assert receipt["performance_results"][1] == {
        "criterion": "p95_frame_time_within_budget",
        "decision": "fail",
    }
    assert receipt["runtime_acceptance_authority"] is False


def test_refresh_fail_blocks_acceptance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    evidence = _evidence()
    evidence["observed_refresh_hz"] = 71.9

    receipt = record_physical_runtime_review(plan, evidence)

    assert receipt["runtime_review_status"] == "fail"
    assert receipt["performance_results"][0]["decision"] == "fail"


def test_device_mismatch_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    evidence = _evidence()
    evidence["target_device_model"] = "quest-3"

    with pytest.raises(
        PhotorealP3PhysicalRuntimeReviewError,
        match="different device class",
    ):
        validate_physical_runtime_evidence(
            evidence,
            runtime_review_plan=plan,
        )


def test_installed_student_hash_mismatch_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    evidence = _evidence()
    evidence["installed_student_artifacts"][0]["sha256"] = "a" * 64

    with pytest.raises(
        PhotorealP3PhysicalRuntimeReviewError,
        match="installed student bytes differ",
    ):
        validate_physical_runtime_evidence(
            evidence,
            runtime_review_plan=plan,
        )


def test_missing_explicit_physical_confirmation_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    evidence = _evidence()
    evidence["confirm_physical_device_review_complete"] = False

    with pytest.raises(
        PhotorealP3PhysicalRuntimeReviewError,
        match="explicit physical-device review completion confirmation",
    ):
        validate_physical_runtime_evidence(
            evidence,
            runtime_review_plan=plan,
        )


def test_resealed_pass_cannot_override_failed_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    receipt = record_physical_runtime_review(plan, _evidence())
    receipt["visual_results"][0]["decision"] = "fail"
    receipt["p3_physical_runtime_review_sha256"] = physical._digest(
        receipt,
        omit="p3_physical_runtime_review_sha256",
    )

    with pytest.raises(
        PhotorealP3PhysicalRuntimeReviewError,
        match="status does not match detailed results",
    ):
        validate_physical_runtime_review_receipt(receipt)


def test_resealed_production_activation_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    receipt = record_physical_runtime_review(plan, _evidence())
    receipt["production_activation"] = True
    receipt["p3_physical_runtime_review_sha256"] = physical._digest(
        receipt,
        omit="p3_physical_runtime_review_sha256",
    )

    with pytest.raises(
        PhotorealP3PhysicalRuntimeReviewError,
        match="production_activation",
    ):
        validate_physical_runtime_review_receipt(receipt)


def test_boolean_v1_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    receipt = record_physical_runtime_review(plan, _evidence())
    receipt["version"] = True
    receipt["p3_physical_runtime_review_sha256"] = physical._digest(
        receipt,
        omit="p3_physical_runtime_review_sha256",
    )

    with pytest.raises(
        PhotorealP3PhysicalRuntimeReviewError,
        match="format/version mismatch",
    ):
        validate_physical_runtime_review_receipt(receipt)
