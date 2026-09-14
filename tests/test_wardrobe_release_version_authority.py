from __future__ import annotations

from typing import Any

import pytest

import bodyrig.wardrobe_release_authority as release


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)
PERSON_ID = "person-" + "1" * 32
PERSON_REVISION = "person-r0001"
BODY_REVISION = "body-r0001"
BODY_ID = "body-" + "2" * 32
PACKAGE_SHA = "3" * 64
ASSEMBLY_SHA = "4" * 64
REVISION = "5" * 40
RELEASE_ID = "wardrelease-" + "6" * 32
REVIEW_ID = "wardreview-" + "7" * 32


def _assembly() -> dict[str, str]:
    return {
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
    }


def _receipt(version: Any) -> dict[str, Any]:
    source_views = {view: "8" * 64 for view in release.REQUIRED_VIEWS}
    render_views = {view: "9" * 64 for view in release.REQUIRED_VIEWS}
    return {
        "format": release.FORMAT,
        "version": version,
        "policy_revision": release.POLICY_REVISION,
        "release_id": RELEASE_ID,
        "review_id": REVIEW_ID,
        "person_id": PERSON_ID,
        "person_revision": PERSON_REVISION,
        "assembly_fingerprint": ASSEMBLY_SHA,
        "body_revision": BODY_REVISION,
        "body_id": BODY_ID,
        "body_package_sha256": PACKAGE_SHA,
        "bodyrig_revision": REVISION,
        "review_authority_sha256": "a" * 64,
        "source_capture_id": "wardcap-" + "b" * 32,
        "source_capture_sha256": "c" * 64,
        "source_manifest_sha256": "d" * 64,
        "source_view_sha256": source_views,
        "garment_inventory_sha256": "e" * 64,
        "garment_count": 1,
        "footwear_present": False,
        "render_authority_sha256": "f" * 64,
        "package_lineage_sha256": "0" * 64,
        "comparison_authority_sha256": "1" * 64,
        "runtime_manifest_sha256": "2" * 64,
        "render_manifest_sha256": "3" * 64,
        "render_view_sha256": render_views,
        "machine_probe_sha256": "4" * 64,
        "deformation_probe_sha256": "5" * 64,
        "deformation_sequence_revision": "humanoid-muscle-sweep-v1",
        "finalized_utc": "2026-09-14T19:00:00Z",
        "state": "complete",
        "source_grounded": True,
        "operator_supplied": True,
        **{field: True for field in release.CHECKLIST_FIELDS},
        "footwear_review_required": False,
        "footwear_review_passed": False,
        "production_activation": False,
    }


def _bind_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    assembly = _assembly()
    monkeypatch.setattr(release, "_assembly_identity", lambda _receipt: dict(assembly))
    monkeypatch.setattr(release, "_release_identity", lambda _status, _assembly: {"package_sha256": PACKAGE_SHA})
    monkeypatch.setattr(release, "_release_id", lambda **_kwargs: RELEASE_ID)


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_finalized_wardrobe_release_rejects_boolean_non_numeric_and_wrong_v1(
    monkeypatch: pytest.MonkeyPatch,
    version: Any,
) -> None:
    _bind_identity(monkeypatch)

    with pytest.raises(
        release.WardrobeReleaseAuthorityError,
        match="finalized wardrobe authority format/version/policy mismatch",
    ):
        release.validate_release_authority_structure(
            _receipt(version),
            assembly_receipt={},
            body_release_status={},
        )


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_finalized_wardrobe_release_preserves_numeric_v1_and_non_production_semantics(
    monkeypatch: pytest.MonkeyPatch,
    version: Any,
) -> None:
    _bind_identity(monkeypatch)

    value = release.validate_release_authority_structure(
        _receipt(version),
        assembly_receipt={},
        body_release_status={},
    )

    assert value["version"] == version
    assert value["person_id"] == PERSON_ID
    assert value["body_id"] == BODY_ID
    assert value["body_package_sha256"] == PACKAGE_SHA
    assert value["garment_count"] == 1
    assert value["footwear_present"] is False
    assert value["footwear_review_required"] is False
    assert value["footwear_review_passed"] is False
    assert all(value[field] is True for field in release.CHECKLIST_FIELDS)
    assert value["source_grounded"] is True
    assert value["operator_supplied"] is True
    assert value["production_activation"] is False
