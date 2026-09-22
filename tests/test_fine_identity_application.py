from __future__ import annotations

import hashlib

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


def _domain_application() -> dict[str, dict[str, bool]]:
    return {
        domain: {
            "geometryApplied": bool(minimum["geometry"]),
            "appearanceApplied": bool(minimum["appearance"]),
        }
        for domain, minimum in subject.REQUIRED_DOMAINS.items()
    }


def test_build_application_binds_exact_attestation_and_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = subject.build_requirement(
        bodyrig_revision="a" * 40,
        fine_identity_authority_sha256="b" * 64,
        fine_identity_attestation_sha256=hashlib.sha256(b"attestation").hexdigest(),
    )
    selected = [
        {"domain": domain, "scene_id": f"{domain}-{index}"}
        for domain in subject.REQUIRED_DOMAINS
        for index in (1, 2)
    ]
    monkeypatch.setattr(
        subject,
        "validate_attestation",
        lambda value, **_kwargs: {**dict(value), "selected_evidence": selected},
    )
    monkeypatch.setattr(
        subject,
        "_avatar_fingerprints",
        lambda avatar: {
            "geometry_surface_sha256": ("1" if avatar == b"source" else "2") * 64,
            "appearance_global_sha256": ("3" if avatar == b"source" else "4") * 64,
            "rig_sha256": "5" * 64,
        },
    )

    value = subject.build_application(
        requirement=requirement,
        attestation={"selected_evidence": selected},
        attestation_bytes=b"attestation",
        source_avatar_vrm=b"source",
        candidate_avatar_vrm=b"candidate",
        domain_application=_domain_application(),
    )

    assert value["fineIdentityAuthoritySha256"] == "b" * 64
    assert value["fineIdentityAttestationSha256"] == hashlib.sha256(b"attestation").hexdigest()
    assert value["sourceGeometrySurfaceSha256"] == "1" * 64
    assert value["candidateGeometrySurfaceSha256"] == "2" * 64
    assert value["sourceAppearanceGlobalSha256"] == "3" * 64
    assert value["candidateAppearanceGlobalSha256"] == "4" * 64
    assert all(item["sourceEvidenceCount"] == 2 for item in value["domains"].values())
    assert value["productionActivation"] is False


def test_build_application_rejects_attestation_byte_drift(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = subject.build_requirement(
        bodyrig_revision="a" * 40,
        fine_identity_authority_sha256="b" * 64,
        fine_identity_attestation_sha256=hashlib.sha256(b"expected").hexdigest(),
    )
    with pytest.raises(subject.FineIdentityApplicationError, match="attestation bytes"):
        subject.build_application(
            requirement=requirement,
            attestation={},
            attestation_bytes=b"changed",
            source_avatar_vrm=b"source",
            candidate_avatar_vrm=b"candidate",
            domain_application=_domain_application(),
        )


def test_build_application_rejects_unchanged_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    requirement = subject.build_requirement(
        bodyrig_revision="a" * 40,
        fine_identity_authority_sha256="b" * 64,
        fine_identity_attestation_sha256=hashlib.sha256(b"attestation").hexdigest(),
    )
    selected = [
        {"domain": domain, "scene_id": f"{domain}-{index}"}
        for domain in subject.REQUIRED_DOMAINS
        for index in (1, 2)
    ]
    monkeypatch.setattr(
        subject,
        "validate_attestation",
        lambda value, **_kwargs: {**dict(value), "selected_evidence": selected},
    )
    monkeypatch.setattr(
        subject,
        "_avatar_fingerprints",
        lambda avatar: {
            "geometry_surface_sha256": "1" * 64,
            "appearance_global_sha256": ("3" if avatar == b"source" else "4") * 64,
            "rig_sha256": "5" * 64,
        },
    )

    with pytest.raises(subject.FineIdentityApplicationError, match="did not change geometry"):
        subject.build_application(
            requirement=requirement,
            attestation={"selected_evidence": selected},
            attestation_bytes=b"attestation",
            source_avatar_vrm=b"source",
            candidate_avatar_vrm=b"candidate",
            domain_application=_domain_application(),
        )
