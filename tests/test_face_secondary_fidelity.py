from __future__ import annotations

import pytest

from bodyrig.face_secondary_fidelity import (
    FaceSecondaryFidelityError,
    current_face_secondary_receipt,
    validate_face_secondary_receipt,
    with_face_secondary_status,
)


def test_current_face_secondary_truth_is_fail_closed() -> None:
    receipt = validate_face_secondary_receipt(current_face_secondary_receipt())

    assert receipt["components"] == {
        "eyebrow_appearance": "not-evaluated",
        "lip_boundary": "not-evaluated",
        "mouth_interior": "missing",
        "teeth": "missing",
        "eyelashes": "missing",
    }
    assert receipt["faceSecondaryReady"] is False
    assert receipt["semanticVertexMapAuthority"] == "unavailable"
    assert receipt["humanReviewRequired"] is True
    assert receipt["productionReady"] is False


def test_geometry_sensitive_component_cannot_complete_without_semantic_authority() -> None:
    receipt = current_face_secondary_receipt()

    with pytest.raises(FaceSecondaryFidelityError, match="semantic authority"):
        with_face_secondary_status(receipt, component="teeth", status="complete")


def test_verified_semantic_authority_can_record_progress_without_readiness() -> None:
    receipt = current_face_secondary_receipt()
    receipt = with_face_secondary_status(
        receipt,
        component="lip_boundary",
        status="complete",
        semantic_vertex_map_authority="licensed-smplx-verified",
    )

    assert receipt["components"]["lip_boundary"] == "complete"
    assert receipt["faceSecondaryReady"] is False
    assert "mouth_interior" in receipt["blockers"]
    assert receipt["productionReady"] is False


def test_face_secondary_only_ready_when_every_subcomponent_is_complete() -> None:
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

    assert receipt["faceSecondaryReady"] is True
    assert receipt["blockers"] == []
    assert receipt["humanReviewRequired"] is True
    assert receipt["productionReady"] is False


def test_face_secondary_rejects_production_or_generative_claim() -> None:
    receipt = current_face_secondary_receipt()
    receipt["productionReady"] = True
    with pytest.raises(FaceSecondaryFidelityError, match="cannot independently authorize production"):
        validate_face_secondary_receipt(receipt)

    receipt = current_face_secondary_receipt()
    receipt["generativeIdentitySynthesis"] = True
    with pytest.raises(FaceSecondaryFidelityError, match="forbidden"):
        validate_face_secondary_receipt(receipt)
