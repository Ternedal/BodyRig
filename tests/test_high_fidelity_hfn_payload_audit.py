from __future__ import annotations

import hashlib

import pytest

import bodyrig.high_fidelity_package_audit as audit


DETAIL_METHOD = "source-landmark-fingernail-toenail-residual-skinned-uv-v3"


def _payload() -> bytes:
    return audit.PNG_SIGNATURE + b"bodyrig-hfn-detail-payload"


def _application(candidate_sha: str) -> dict[str, object]:
    return {
        "format": audit.HFN_APPLICATION_FORMAT,
        "version": 1,
        "policyRevision": audit.HFN_POLICY_REVISION,
        "candidateId": "hfncand-" + "1" * 32,
        "personId": "person-" + "2" * 32,
        "bodyRevision": "body-r0001",
        "captureId": "hfncap-" + "3" * 32,
        "bodyrigRevision": "4" * 40,
        "method": DETAIL_METHOD,
        "sourcePackageSha256": "5" * 64,
        "sourceCaptureSha256": "6" * 64,
        "landmarkEvidenceSha256": "7" * 64,
        "uvEvidenceSha256": "8" * 64,
        "sourceBaseColorSha256": "9" * 64,
        "candidateBaseColorSha256": candidate_sha,
        "maxChannelDeltaLevels": 24,
        "regions": {
            "left_hand": {},
            "right_hand": {},
            "left_foot": {},
            "right_foot": {},
        },
        "geometrySurfaceSha256": "a" * 64,
        "skinnedSurfaceSha256": "b" * 64,
        "rigSha256": "c" * 64,
        "uvMaterialMappingSha256": "d" * 64,
        "sourceGrounded": True,
        "generative": False,
        "packageApplicationAuthority": True,
        "geometryModified": False,
        "textureModified": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }


def _document(payload: bytes, *, candidate_sha: str | None = None) -> tuple[dict[str, object], dict[str, object]]:
    sha = candidate_sha or hashlib.sha256(payload).hexdigest()
    bodyrig: dict[str, object] = {
        "appearanceTransfer": {"activeBaseColorSha256": sha},
        "handsFeetNailsDetailApplication": _application(sha),
    }
    document: dict[str, object] = {
        "images": [
            {
                "name": audit.HFN_IMAGE,
                "bufferView": 0,
                "mimeType": "image/png",
            }
        ],
        "textures": [{"source": 0}],
        "materials": [
            {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(payload)}
        ],
    }
    return document, bodyrig


def test_hfn_payload_audit_binds_application_to_active_body_texture_bytes() -> None:
    payload = _payload()
    document, bodyrig = _document(payload)

    result = audit._audit_hfn_payload(document, payload, bodyrig)

    assert result is not None
    assert result["image"] == 0
    assert result["buffer_view"] == 0
    assert result["base_color_sha256"] == hashlib.sha256(payload).hexdigest()
    assert result["method"] == DETAIL_METHOD


def test_hfn_payload_audit_rejects_tampered_active_texture_bytes() -> None:
    original = _payload()
    expected_sha = hashlib.sha256(original).hexdigest()
    tampered = original + b"tampered"
    document, bodyrig = _document(tampered, candidate_sha=expected_sha)

    with pytest.raises(
        audit.HighFidelityPackageAuditError,
        match="active base-color bytes do not match candidate authority",
    ):
        audit._audit_hfn_payload(document, tampered, bodyrig)


def test_hfn_payload_audit_rejects_metadata_not_bound_to_active_appearance() -> None:
    payload = _payload()
    document, bodyrig = _document(payload)
    bodyrig["appearanceTransfer"] = {"activeBaseColorSha256": "e" * 64}

    with pytest.raises(
        audit.HighFidelityPackageAuditError,
        match="candidate hash is not the active appearanceTransfer base color",
    ):
        audit._audit_hfn_payload(document, payload, bodyrig)


def test_hfn_payload_audit_rejects_noncanonical_application_fields() -> None:
    payload = _payload()
    document, bodyrig = _document(payload)
    application = dict(bodyrig["handsFeetNailsDetailApplication"])
    application["untrusted"] = True
    bodyrig["handsFeetNailsDetailApplication"] = application

    with pytest.raises(
        audit.HighFidelityPackageAuditError,
        match="metadata fields are not canonical",
    ):
        audit._audit_hfn_payload(document, payload, bodyrig)


def test_hfn_payload_audit_rejects_body_material_not_using_detail_image() -> None:
    payload = _payload()
    document, bodyrig = _document(payload)
    document["materials"] = [
        {"pbrMetallicRoughness": {"baseColorTexture": {"index": 1}}}
    ]

    with pytest.raises(
        audit.HighFidelityPackageAuditError,
        match="not bound to body material 0 base color",
    ):
        audit._audit_hfn_payload(document, payload, bodyrig)
