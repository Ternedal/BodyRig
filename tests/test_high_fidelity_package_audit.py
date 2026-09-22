from __future__ import annotations

import pytest

import bodyrig.high_fidelity_package_audit as package_audit
from bodyrig.fine_identity_application import build_requirement

from bodyrig.bridges.avatar_fidelity_components import (
    current_pipeline_receipt,
    with_component_status,
    with_face_secondary_receipt,
)
from bodyrig.bridges.face_secondary_fidelity import (
    REQUIRED_SUBCOMPONENTS,
    current_face_secondary_receipt,
    with_face_secondary_status,
)
from bodyrig.high_fidelity_package_audit import (
    HighFidelityPackageAuditError,
    audit_fidelity_document,
)


def _document(*, top=None, face=None, **bodyrig_fields) -> dict:
    bodyrig = dict(bodyrig_fields)
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
    assert result["render_payloads"] == {}
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


def test_hair_complete_requires_concrete_render_payload() -> None:
    top = with_component_status(current_pipeline_receipt(), component="hair", status="complete")
    with pytest.raises(HighFidelityPackageAuditError, match="hair render payload requires glTF nodes array"):
        audit_fidelity_document(
            _document(
                top=top,
                face=current_face_secondary_receipt(),
                hairPromotion={
                    "format": "bodyrig-hair-promotion",
                    "version": 1,
                    "component": "hair",
                    "eyesImported": False,
                    "productionActivation": False,
                },
            )
        )


def test_hair_promotion_rejects_boolean_v1() -> None:
    top = with_component_status(current_pipeline_receipt(), component="hair", status="complete")
    with pytest.raises(
        HighFidelityPackageAuditError,
        match="hair=complete with invalid embedded hairPromotion authority",
    ):
        audit_fidelity_document(
            _document(
                top=top,
                face=current_face_secondary_receipt(),
                hairPromotion={
                    "format": "bodyrig-hair-promotion",
                    "version": True,
                    "component": "hair",
                    "eyesImported": False,
                    "productionActivation": False,
                },
            )
        )


def test_eyes_complete_requires_concrete_render_payload() -> None:
    top = with_component_status(current_pipeline_receipt(), component="eyes", status="complete")
    with pytest.raises(HighFidelityPackageAuditError, match="eyes render payload requires glTF nodes array"):
        audit_fidelity_document(
            _document(
                top=top,
                face=current_face_secondary_receipt(),
                eyePromotion={
                    "format": "bodyrig-eye-promotion",
                    "version": 1,
                    "component": "eyes",
                    "sourceEyeRuntimeImported": True,
                    "sourceHairRuntimeImported": False,
                    "productionActivation": False,
                },
            )
        )


def test_face_secondary_complete_requires_concrete_render_payload() -> None:
    face = current_face_secondary_receipt()
    for component in REQUIRED_SUBCOMPONENTS:
        face = with_face_secondary_status(
            face,
            component=component,
            status="complete",
            semantic_vertex_map_authority="licensed-smplx-verified",
        )
    top = with_face_secondary_receipt(
        current_pipeline_receipt(),
        face_secondary_receipt=face,
    )

    with pytest.raises(
        HighFidelityPackageAuditError,
        match="face_secondary render payload requires glTF nodes array",
    ):
        audit_fidelity_document(
            _document(
                top=top,
                face=face,
                faceSecondaryPromotion={
                    "format": "bodyrig-face-secondary-promotion",
                    "version": 1,
                    "component": "face_secondary",
                    "productionActivation": False,
                },
            )
        )


def _source_dental_face_document() -> tuple[dict, dict]:
    requirement = build_requirement(
        bodyrig_revision="a" * 40,
        fine_identity_authority_sha256="b" * 64,
        fine_identity_attestation_sha256="c" * 64,
    )
    promotion = {
        "format": "bodyrig-face-secondary-promotion",
        "version": 1,
        "component": "face_secondary",
        "sourceDerivedDentalIdentity": True,
        "genericSecondaryAnatomy": False,
        "dentalSourceVrmSha256": "d" * 64,
        "dentalReconstructionResultSha256": "e" * 64,
        "fineIdentityAttestationSha256": "c" * 64,
        "fineIdentityAuthoritySha256": "b" * 64,
        "dentalSourceReferences": ["oral-a", "oral-b"],
        "productionActivation": False,
    }
    document = {
        "materials": [
            {"name": "BodyRigEyelashesReview"},
            {"name": package_audit.GRAFT_MOUTH_MATERIAL},
            {"name": package_audit.GRAFT_DENTAL_MATERIAL},
        ],
        "meshes": [
            {
                "name": package_audit.FACE_MESH,
                "primitives": [
                    {"attributes": {"POSITION": 0}, "material": 0},
                ],
            },
            {
                "name": package_audit.GRAFT_MESH_NAME,
                "primitives": [
                    {
                        "attributes": {"POSITION": 1},
                        "material": 1,
                        "extras": {"bodyrigDentalRole": "mouth_interior"},
                    },
                    {
                        "attributes": {"POSITION": 2},
                        "material": 2,
                        "extras": {"bodyrigDentalRole": "upper_teeth"},
                    },
                    {
                        "attributes": {"POSITION": 3},
                        "material": 2,
                        "extras": {"bodyrigDentalRole": "lower_teeth"},
                    },
                ],
            },
        ],
        "nodes": [
            {"name": package_audit.FACE_NODE, "mesh": 0, "skin": 0},
            {"name": package_audit.GRAFT_NODE_NAME, "mesh": 1, "skin": 0},
        ],
        "scenes": [{"nodes": [0, 1]}],
    }
    bodyrig = {
        "faceSecondaryPromotion": promotion,
        "fineIdentityRequirement": requirement,
    }
    return document, bodyrig


def test_source_derived_dental_face_payload_has_strict_separate_graft_contract() -> None:
    document, bodyrig = _source_dental_face_document()

    result = package_audit._audit_face_payload(document, bodyrig)

    assert result["source_derived_dental_identity"] is True
    assert result["materials"] == {"BodyRigEyelashesReview": 0}
    assert result["source_dental"]["roles"] == [
        "lower_teeth",
        "mouth_interior",
        "upper_teeth",
    ]
    assert result["source_dental"]["materials"] == {"mouth": 1, "dental": 2}


def test_source_derived_dental_face_payload_rejects_missing_graft() -> None:
    document, bodyrig = _source_dental_face_document()
    document["nodes"] = [document["nodes"][0]]
    document["meshes"] = [document["meshes"][0]]
    document["scenes"] = [{"nodes": [0]}]

    with pytest.raises(
        HighFidelityPackageAuditError,
        match="source-derived dental render payload requires exactly one nodes entry",
    ):
        package_audit._audit_face_payload(document, bodyrig)


def test_source_derived_dental_face_payload_rejects_lineage_drift() -> None:
    document, bodyrig = _source_dental_face_document()
    bodyrig["faceSecondaryPromotion"]["fineIdentityAuthoritySha256"] = "9" * 64

    with pytest.raises(
        HighFidelityPackageAuditError,
        match="lost fine-identity lineage",
    ):
        package_audit._audit_face_payload(document, bodyrig)
