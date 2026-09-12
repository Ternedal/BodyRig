from __future__ import annotations

import pytest

import bodyrig.digital_twin_composition_authority as m4


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
REVISION = "1" * 40


def _component(value: dict, exact_sha: str) -> dict:
    return {
        "release_id": value["release_id"],
        "review_id": value["review_id"],
        "source_capture_id": value["source_capture_id"],
        "authority_sha256": exact_sha,
        "authority_content_sha256": m4._content_sha256(value),
    }


def _inputs(monkeypatch: pytest.MonkeyPatch, version: object) -> tuple[dict, dict, dict, dict, dict]:
    assembly = {"audition": {"receipt_sha256": SHA_A}}
    body_release = {"fixture": "release"}
    hands = {
        "release_id": "hfnrelease-fixture",
        "review_id": "hfnreview-fixture",
        "source_capture_id": "hfncap-fixture",
        "bodyrig_revision": REVISION,
    }
    wardrobe = {
        "release_id": "wardrelease-fixture",
        "review_id": "wardreview-fixture",
        "source_capture_id": "wardcap-fixture",
        "bodyrig_revision": REVISION,
    }
    identity = {
        "person_id": "person-0123456789abcdef0123456789abcdef",
        "person_revision": "person-r0001",
        "assembly_fingerprint": SHA_B,
        "body_revision": "body-r0001",
        "body_id": "body-0123456789abcdef0123456789abcdef",
    }
    release_identity = {"package_sha256": SHA_C}

    monkeypatch.setattr(m4, "_assembly_identity", lambda value: identity)
    monkeypatch.setattr(m4, "_release_identity", lambda value, assembly_identity: release_identity)
    monkeypatch.setattr(
        m4,
        "validate_hands_nails_release_authority",
        lambda value, **kwargs: hands,
    )
    monkeypatch.setattr(
        m4,
        "validate_wardrobe_release_authority",
        lambda value, **kwargs: wardrobe,
    )

    authority = {
        "format": m4.FORMAT,
        "version": version,
        "policy_revision": m4.POLICY_REVISION,
        "authority_id": "",
        **identity,
        "body_package_sha256": SHA_C,
        "bodyprint_sha256": SHA_D,
        "bodyrig_revision": REVISION,
        "assembly_receipt_sha256": SHA_E,
        "assembly_receipt_content_sha256": m4._content_sha256(assembly),
        "body_release_status_sha256": SHA_F,
        "body_release_status_content_sha256": m4._content_sha256(body_release),
        "audition_receipt_sha256": SHA_A,
        "hands_feet_nails": _component(hands, "2" * 64),
        "wardrobe": _component(wardrobe, "3" * 64),
        "embodiment_probe_sha256": "4" * 64,
        "finalized_utc": "2026-09-12T20:00:00Z",
        "state": "complete",
        "source_observed_embodiment": True,
        "production_activation": False,
    }
    authority["authority_id"] = m4._authority_id(authority)
    return authority, assembly, body_release, hands, wardrobe


def _validate(monkeypatch: pytest.MonkeyPatch, version: object) -> dict:
    authority, assembly, body_release, hands, wardrobe = _inputs(monkeypatch, version)
    return m4.validate_composition_authority_structure(
        authority,
        assembly_receipt=assembly,
        body_release_status=body_release,
        hands_nails_authority=hands,
        wardrobe_authority=wardrobe,
    )


def test_m4_rejects_boolean_v1_version(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(m4.DigitalTwinCompositionAuthorityError, match="format/version/policy"):
        _validate(monkeypatch, True)


def test_m4_preserves_numeric_v1_compatibility(monkeypatch: pytest.MonkeyPatch) -> None:
    validated = _validate(monkeypatch, 1.0)
    assert validated["version"] == 1.0
    assert validated["state"] == "complete"
    assert validated["production_activation"] is False
