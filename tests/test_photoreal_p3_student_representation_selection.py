from __future__ import annotations

import copy

import pytest

import bodyrig.photoreal_p3_student_representation_selection as selection
from bodyrig.photoreal_p3_device_distillation_plan import (
    CANDIDATE_STUDENT_REPRESENTATIONS,
)
from bodyrig.photoreal_p3_student_representation_selection import (
    PhotorealP3StudentRepresentationSelectionError,
    build_p3_student_representation_selection,
    require_p3_adapter_selection_authority,
    validate_p3_student_representation_selection,
)


def _plan(target_model: str = "quest-2") -> dict[str, object]:
    return {
        "performer_id": "42",
        "selected_epoch_id": "epoch-a",
        "p3_device_distillation_plan_sha256": "1" * 64,
        "target_profile_sha256": "2" * 64,
        "accepted_teacher_checkpoint_sha256": "3" * 64,
        "candidate_student_representations": list(CANDIDATE_STUDENT_REPRESENTATIONS),
        "target_profile": {"target_model": target_model},
        "p3_distillation_execution_authorized": True,
    }


def _trust(monkeypatch: pytest.MonkeyPatch, plan: dict[str, object]) -> None:
    monkeypatch.setattr(
        selection,
        "require_p3_distillation_execution_authority",
        lambda value: plan,
    )


def test_quest2_selects_hybrid_student_without_starting_distillation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan("quest-2")
    _trust(monkeypatch, plan)

    receipt = build_p3_student_representation_selection(
        plan,
        primary_representation="hybrid-mesh-neural-residual",
        optional_components=(
            "specialized-eye-component",
            "teacher-derived-hair-component",
        ),
    )
    validated = validate_p3_student_representation_selection(receipt)

    assert validated["target_model"] == "quest-2"
    assert validated["primary_representation"] == "hybrid-mesh-neural-residual"
    assert validated["optional_components"] == [
        "specialized-eye-component",
        "teacher-derived-hair-component",
    ]
    assert validated["native_gaussian_dependency_selected"] is False
    assert validated["student_representation_selected"] is True
    assert validated["distillation_adapter_selected"] is False
    assert validated["distillation_job_start_authorized"] is False
    assert validated["runtime_acceptance_authority"] is False
    assert validated["production_activation"] is False
    assert require_p3_adapter_selection_authority(validated) == validated


def test_quest2_rejects_native_gaussian_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan("quest-2")
    _trust(monkeypatch, plan)

    with pytest.raises(
        PhotorealP3StudentRepresentationSelectionError,
        match="Quest 2.*native Gaussian splats",
    ):
        build_p3_student_representation_selection(
            plan,
            primary_representation="gaussian-splat-optional",
        )


@pytest.mark.parametrize("model", ["quest-3", "quest-3s"])
def test_quest3_family_may_select_optional_gaussian_primary(
    monkeypatch: pytest.MonkeyPatch,
    model: str,
) -> None:
    plan = _plan(model)
    _trust(monkeypatch, plan)

    receipt = build_p3_student_representation_selection(
        plan,
        primary_representation="gaussian-splat-optional",
    )
    assert receipt["native_gaussian_dependency_selected"] is True
    assert receipt["distillation_job_start_authorized"] is False


def test_component_cannot_be_used_as_primary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)

    with pytest.raises(
        PhotorealP3StudentRepresentationSelectionError,
        match="primary student representation is unsupported",
    ):
        build_p3_student_representation_selection(
            plan,
            primary_representation="specialized-eye-component",
        )


def test_optional_components_must_be_unique(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)

    with pytest.raises(
        PhotorealP3StudentRepresentationSelectionError,
        match="must be unique",
    ):
        build_p3_student_representation_selection(
            plan,
            primary_representation="hybrid-mesh-neural-residual",
            optional_components=(
                "specialized-eye-component",
                "specialized-eye-component",
            ),
        )


def test_plan_candidate_universe_cannot_be_narrowed_before_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    plan["candidate_student_representations"] = ["hybrid-mesh-neural-residual"]
    _trust(monkeypatch, plan)

    with pytest.raises(
        PhotorealP3StudentRepresentationSelectionError,
        match="candidate universe",
    ):
        build_p3_student_representation_selection(
            plan,
            primary_representation="hybrid-mesh-neural-residual",
        )


def test_readback_rejects_resealed_adapter_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    receipt = build_p3_student_representation_selection(
        plan,
        primary_representation="hybrid-mesh-neural-residual",
    )
    tampered = copy.deepcopy(receipt)
    tampered["distillation_adapter_selected"] = True
    tampered["p3_student_representation_selection_sha256"] = selection._digest(
        tampered,
        omit="p3_student_representation_selection_sha256",
    )

    with pytest.raises(
        PhotorealP3StudentRepresentationSelectionError,
        match="distillation_adapter_selected",
    ):
        validate_p3_student_representation_selection(tampered)


def test_readback_rejects_resealed_production_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan = _plan()
    _trust(monkeypatch, plan)
    receipt = build_p3_student_representation_selection(
        plan,
        primary_representation="hybrid-mesh-neural-residual",
    )
    tampered = copy.deepcopy(receipt)
    tampered["production_activation"] = True
    tampered["p3_student_representation_selection_sha256"] = selection._digest(
        tampered,
        omit="p3_student_representation_selection_sha256",
    )

    with pytest.raises(
        PhotorealP3StudentRepresentationSelectionError,
        match="production_activation",
    ):
        validate_p3_student_representation_selection(tampered)


def test_readback_rejects_boolean_version() -> None:
    value = {
        "format": selection.FORMAT,
        "version": True,
    }
    with pytest.raises(
        PhotorealP3StudentRepresentationSelectionError,
        match="fields must match v1 exactly|format/version mismatch",
    ):
        validate_p3_student_representation_selection(value)
