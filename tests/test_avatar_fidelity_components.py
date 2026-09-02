from __future__ import annotations

from bodyrig.bridges.avatar_fidelity_components import (
    FidelityComponentError,
    current_pipeline_receipt,
    validate_receipt,
    with_component_status,
)


def test_current_pipeline_truthfully_blocks_high_fidelity() -> None:
    receipt = current_pipeline_receipt(reconstruction_gender="female")
    validated = validate_receipt(receipt)

    assert validated["components"] == {
        "body_anatomy": "not-evaluated",
        "skin_appearance": "partial",
        "hair": "missing",
        "eyes": "missing",
        "face_secondary": "missing",
    }
    assert validated["highFidelityReady"] is False
    assert validated["productionReady"] is False
    assert validated["blockers"] == [
        "body_anatomy",
        "skin_appearance",
        "hair",
        "eyes",
        "face_secondary",
    ]


def test_components_only_reach_high_fidelity_when_every_gate_is_complete() -> None:
    receipt = current_pipeline_receipt(reconstruction_gender="female")
    for component in (
        "body_anatomy",
        "skin_appearance",
        "hair",
        "eyes",
        "face_secondary",
    ):
        receipt = with_component_status(receipt, component=component, status="complete")

    validated = validate_receipt(receipt)
    assert validated["highFidelityReady"] is True
    assert validated["blockers"] == []
    assert validated["humanReviewRequired"] is True
    assert validated["productionReady"] is False


def test_component_receipt_rejects_inconsistent_ready_claim() -> None:
    receipt = current_pipeline_receipt(reconstruction_gender="female")
    receipt["highFidelityReady"] = True

    try:
        validate_receipt(receipt)
    except FidelityComponentError as exc:
        assert "readiness is inconsistent" in str(exc)
    else:
        raise AssertionError("inconsistent high-fidelity readiness was accepted")


def test_component_receipt_rejects_production_authorization() -> None:
    receipt = current_pipeline_receipt(reconstruction_gender="female")
    receipt["productionReady"] = True

    try:
        validate_receipt(receipt)
    except FidelityComponentError as exc:
        assert "cannot independently authorize production" in str(exc)
    else:
        raise AssertionError("component receipt authorized production")
