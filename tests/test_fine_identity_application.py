from __future__ import annotations

import pytest

import bodyrig.fine_identity_application as subject


def test_requirement_is_strict_and_non_activating() -> None:
    value = subject.build_requirement(
        bodyrig_revision="a" * 40,
        fine_identity_authority_sha256="b" * 64,
        fine_identity_attestation_sha256="c" * 64,
    )
    assert value["sourceGroundedRequired"] is True
    assert value["applicationRequired"] is True
    assert value["genericGuessingPermitted"] is False
    assert value["productionActivation"] is False


def test_application_requires_full_domain_set(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = subject.build_requirement(
        bodyrig_revision="a" * 40,
        fine_identity_authority_sha256="b" * 64,
        fine_identity_attestation_sha256="c" * 64,
    )
    domains = {
        domain: {
            "sourceEvidenceCount": 2,
            "geometryApplied": bool(minimum["geometry"]),
            "appearanceApplied": bool(minimum["appearance"]),
        }
        for domain, minimum in subject.REQUIRED_DOMAINS.items()
    }
    value = {
        "format": subject.APPLICATION_FORMAT,
        "version": subject.VERSION,
        "policyRevision": subject.POLICY_REVISION,
        "bodyrigRevision": "a" * 40,
        "fineIdentityAuthoritySha256": "b" * 64,
        "fineIdentityAttestationSha256": "c" * 64,
        "domains": domains,
        "sourceGeometrySurfaceSha256": "d" * 64,
        "candidateGeometrySurfaceSha256": "e" * 64,
        "sourceAppearanceGlobalSha256": "f" * 64,
        "candidateAppearanceGlobalSha256": "1" * 64,
        "sourceGrounded": True,
        "generative": False,
        "packageApplicationAuthority": True,
        "geometryModified": True,
        "appearanceModified": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    monkeypatch.setattr(
        subject,
        "_avatar_fingerprints",
        lambda _avatar: {
            "geometry_surface_sha256": "e" * 64,
            "appearance_global_sha256": "1" * 64,
        },
    )
    assert subject.validate_application(value, requirement=requirement, avatar_vrm=b"vrm")["packageApplicationAuthority"] is True

    broken = dict(value)
    broken_domains = dict(domains)
    broken_domains.pop("intimate_anatomy_detail")
    broken["domains"] = broken_domains
    with pytest.raises(subject.FineIdentityApplicationError, match="domain set is incomplete"):
        subject.validate_application(broken, requirement=requirement, avatar_vrm=b"vrm")
