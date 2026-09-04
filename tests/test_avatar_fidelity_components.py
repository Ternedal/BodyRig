from __future__ import annotations

from bodyrig.bridges.avatar_fidelity_components import (
    FidelityComponentError,
    current_pipeline_receipt,
    validate_receipt,
    with_component_status,
    with_face_secondary_receipt,
)
from bodyrig.bridges.face_secondary_fidelity import (
    current_face_secondary_receipt,
    with_face_secondary_status,
)


def test_current_pipeline_truthfully_blocks_high_fidelity() -> None:
    receipt = current_pipeline_receipt()
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


def _complete_face_secondary_receipt():
    receipt = current_face_secondary_receipt()
    for component in (
        "eyebrow_appearance",
        "lip_boundary",
        "mouth_interior",
        "teeth",
        "eyelashes",
    ):
        receipt = with_face_secondary_status(
            receipt,
            component=component,
            status="complete",
            semantic_vertex_map_authority="source-evidence-verified",
        )
    return receipt


def test_components_only_reach_high_fidelity_when_every_gate_is_complete() -> None:
    receipt = current_pipeline_receipt()
    for component in (
        "body_anatomy",
        "skin_appearance",
        "hair",
        "eyes",
    ):
        receipt = with_component_status(receipt, component=component, status="complete")
    receipt = with_face_secondary_receipt(
        receipt,
        face_secondary_receipt=_complete_face_secondary_receipt(),
    )

    validated = validate_receipt(receipt)
    assert validated["highFidelityReady"] is True
    assert validated["blockers"] == []
    assert validated["humanReviewRequired"] is True
    assert validated["productionReady"] is False


def test_face_secondary_cannot_be_completed_directly() -> None:
    receipt = current_pipeline_receipt()

    try:
        with_component_status(receipt, component="face_secondary", status="complete")
    except FidelityComponentError as exc:
        assert "validated face-secondary receipt" in str(exc)
    else:
        raise AssertionError("face_secondary bypassed its subcomponent receipt")


def test_incomplete_face_secondary_receipt_cannot_clear_top_level_blocker() -> None:
    receipt = current_pipeline_receipt()
    next_receipt = with_face_secondary_receipt(
        receipt,
        face_secondary_receipt=current_face_secondary_receipt(),
    )

    assert next_receipt["components"]["face_secondary"] == "missing"
    assert "face_secondary" in next_receipt["blockers"]
    assert next_receipt["highFidelityReady"] is False


def test_component_receipt_rejects_inconsistent_ready_claim() -> None:
    receipt = current_pipeline_receipt()
    receipt["highFidelityReady"] = True

    try:
        validate_receipt(receipt)
    except FidelityComponentError as exc:
        assert "readiness is inconsistent" in str(exc)
    else:
        raise AssertionError("inconsistent high-fidelity readiness was accepted")


def test_component_receipt_rejects_production_authorization() -> None:
    receipt = current_pipeline_receipt()
    receipt["productionReady"] = True

    try:
        validate_receipt(receipt)
    except FidelityComponentError as exc:
        assert "cannot independently authorize production" in str(exc)
    else:
        raise AssertionError("component receipt authorized production")
