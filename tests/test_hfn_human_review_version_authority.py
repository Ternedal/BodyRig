from __future__ import annotations

from typing import Any

import pytest

import bodyrig.hands_feet_nails_authority as authority


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)
PERSON_ID = "person-0123456789abcdef0123456789abcdef"
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-0123456789abcdef0123456789abcdef"
PACKAGE_SHA = "b" * 64
ASSEMBLY_SHA = "a" * 64
BODYRIG_REVISION = "1" * 40
REVIEW_ID = "hfnreview-" + "2" * 32
CAPTURE_ID = "hfncap-" + "3" * 32


def _assembly_identity() -> dict[str, str]:
    return {
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
    }


def _release_status(version: Any) -> dict[str, Any]:
    return {
        "format": "bodyrig-person-release-status",
        "version": version,
        "person_id": PERSON_ID,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "package_sha256": PACKAGE_SHA,
        "production_ready": False,
        "production_activation": False,
    }


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_hfn_body_release_identity_rejects_boolean_non_numeric_and_wrong_v1(version: Any) -> None:
    with pytest.raises(
        authority.HandsFeetNailsAuthorityError,
        match="requires canonical Person body-release status v1",
    ):
        authority._release_identity(_release_status(version), _assembly_identity())


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_hfn_body_release_identity_preserves_numeric_v1_and_exact_package_binding(version: Any) -> None:
    value = authority._release_identity(_release_status(version), _assembly_identity())

    assert value == {"package_sha256": PACKAGE_SHA}


def _review_receipt(version: Any) -> dict[str, Any]:
    source_regions = {region: "4" * 64 for region in authority.REQUIRED_REGIONS}
    render_regions = {region: "5" * 64 for region in authority.REQUIRED_REGIONS}
    checklist = {field: True for field in authority.CHECKLIST_FIELDS}
    return {
        "format": authority.FORMAT,
        "version": version,
        "policy_revision": authority.POLICY_REVISION,
        "review_id": REVIEW_ID,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": BODYRIG_REVISION,
        "source_capture_id": CAPTURE_ID,
        "source_capture_sha256": "6" * 64,
        "source_manifest_sha256": "7" * 64,
        "source_region_sha256": source_regions,
        "render_manifest_sha256": "8" * 64,
        "render_region_sha256": render_regions,
        "reviewed_utc": "2026-09-14T19:00:00Z",
        "checklist": checklist,
        "quality_note": "Hands, feet, fingers, toes, skin detail and nails match the reviewed source closeups.",
        "state": "complete",
        "source_grounded": True,
        "operator_supplied": True,
        **checklist,
        "production_activation": False,
    }


def _bind_review_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    assembly = _assembly_identity()
    monkeypatch.setattr(authority, "_assembly_identity", lambda _receipt: dict(assembly))
    monkeypatch.setattr(authority, "_release_identity", lambda _status, _assembly: {"package_sha256": PACKAGE_SHA})
    monkeypatch.setattr(authority, "_review_id", lambda **_kwargs: REVIEW_ID)


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_hfn_human_review_authority_rejects_boolean_non_numeric_and_wrong_v1(
    monkeypatch: pytest.MonkeyPatch,
    version: Any,
) -> None:
    _bind_review_identity(monkeypatch)

    with pytest.raises(
        authority.HandsFeetNailsAuthorityError,
        match="hands/feet/nails authority format/version/policy mismatch",
    ):
        authority.validate_authority_structure(
            _review_receipt(version),
            assembly_receipt={},
            body_release_status={},
        )


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_hfn_human_review_authority_preserves_numeric_v1_and_review_only_semantics(
    monkeypatch: pytest.MonkeyPatch,
    version: Any,
) -> None:
    _bind_review_identity(monkeypatch)

    value = authority.validate_authority_structure(
        _review_receipt(version),
        assembly_receipt={},
        body_release_status={},
    )

    assert value["version"] == version
    assert value["person_id"] == PERSON_ID
    assert value["body_id"] == BODY_ID
    assert value["body_package_sha256"] == PACKAGE_SHA
    assert value["state"] == "complete"
    assert value["source_grounded"] is True
    assert value["operator_supplied"] is True
    assert all(value[field] is True for field in authority.CHECKLIST_FIELDS)
    assert value["production_activation"] is False
