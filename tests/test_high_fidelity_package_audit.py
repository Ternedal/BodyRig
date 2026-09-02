from __future__ import annotations

import pytest

from bodyrig.bridges.avatar_fidelity_components import (
    current_pipeline_receipt,
    with_component_status,
)
from bodyrig.bridges.face_secondary_fidelity import current_face_secondary_receipt
from bodyrig.high_fidelity_package_audit import (
    HighFidelityPackageAuditError,
    audit_fidelity_document,
)


def _document(*, top=None, face=None) -> dict:
    bodyrig = {}
    if top is not None:
        bodyrig["fidelityComponents"] = top
    if face is not None:
        bodyrig["faceSecondaryFidelity"] = face
    return {"extras": {"bodyrig": bodyrig}}


def test_current_nested_receipts_audit_fail_closed() -> None:
    result = audit_fidelity_document(
        _document(
            top=current_pipeline_receipt(),
            face=current_face_secondary_receipt(),
        )
    )

    assert result["components"]["face_secondary"] == "missing"
    assert result["high_fidelity_ready"] is False
    assert result["face_secondary_ready"] is False
    assert result["face_secondary_components"] == {
        "eyebrow_appearance": "not-evaluated",
        "lip_boundary": "not-evaluated",
        "mouth_interior": "missing",
        "teeth": "missing",
        "eyelashes": "missing",
    }
    assert result["semantic_vertex_map_authority"] == "unavailable"
    assert result["human_review_required"] is True
    assert result["production_ready"] is False


def test_audit_rejects_top_level_face_status_inconsistent_with_nested_receipt() -> None:
    top = with_component_status(
        current_pipeline_receipt(),
        component="face_secondary",
        status="partial",
    )

    with pytest.raises(HighFidelityPackageAuditError, match="inconsistent with nested"):
        audit_fidelity_document(
            _document(top=top, face=current_face_secondary_receipt())
        )


def test_audit_rejects_missing_nested_face_receipt() -> None:
    with pytest.raises(HighFidelityPackageAuditError, match="faceSecondaryFidelity receipt is missing"):
        audit_fidelity_document(_document(top=current_pipeline_receipt()))


def test_audit_rejects_missing_top_level_receipt() -> None:
    with pytest.raises(HighFidelityPackageAuditError, match="fidelityComponents receipt is missing"):
        audit_fidelity_document(_document(face=current_face_secondary_receipt()))
