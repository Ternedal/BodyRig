from __future__ import annotations

import hashlib
import re
from typing import Any, Mapping

from .fidelity_ab import FidelityAbError, _avatar_fingerprints
from .photoidentity_fine_identity_attestation import (
    PhotoIdentityFineIdentityAttestationError,
    validate_attestation,
)

REQUIREMENT_FORMAT = "bodyrig-fine-identity-requirement"
APPLICATION_FORMAT = "bodyrig-fine-identity-application"
VERSION = 1
POLICY_REVISION = "bodyrig-fine-identity-application-v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_DOMAINS = {
    "oral_teeth_detail": {"geometry": True, "appearance": True},
    "chest_breast_shape_detail": {"geometry": True, "appearance": True},
    "nipple_areola_detail": {"geometry": False, "appearance": True},
    "intimate_anatomy_detail": {"geometry": True, "appearance": True},
    "distinctive_markers_detail": {"geometry": False, "appearance": True},
}

REQUIREMENT_FIELDS = {
    "format",
    "version",
    "policyRevision",
    "bodyrigRevision",
    "fineIdentityAuthoritySha256",
    "fineIdentityAttestationSha256",
    "sourceGroundedRequired",
    "applicationRequired",
    "genericGuessingPermitted",
    "productionActivation",
}

APPLICATION_FIELDS = {
    "format",
    "version",
    "policyRevision",
    "bodyrigRevision",
    "fineIdentityAuthoritySha256",
    "fineIdentityAttestationSha256",
    "domains",
    "sourceGeometrySurfaceSha256",
    "candidateGeometrySurfaceSha256",
    "sourceAppearanceGlobalSha256",
    "candidateAppearanceGlobalSha256",
    "sourceGrounded",
    "generative",
    "packageApplicationAuthority",
    "geometryModified",
    "appearanceModified",
    "humanReviewRequired",
    "productionActivation",
}

DOMAIN_FIELDS = {
    "sourceEvidenceCount",
    "geometryApplied",
    "appearanceApplied",
}


class FineIdentityApplicationError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA256_RE.fullmatch(text):
        raise FineIdentityApplicationError(f"{label} is not a canonical SHA-256")
    return text


def _revision(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise FineIdentityApplicationError("fine-identity BodyRig revision is not canonical")
    return text


def build_requirement(
    *,
    bodyrig_revision: str,
    fine_identity_authority_sha256: str,
    fine_identity_attestation_sha256: str,
) -> dict[str, Any]:
    value = {
        "format": REQUIREMENT_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "bodyrigRevision": _revision(bodyrig_revision),
        "fineIdentityAuthoritySha256": _sha(
            fine_identity_authority_sha256,
            label="fine-identity authority SHA-256",
        ),
        "fineIdentityAttestationSha256": _sha(
            fine_identity_attestation_sha256,
            label="fine-identity attestation SHA-256",
        ),
        "sourceGroundedRequired": True,
        "applicationRequired": True,
        "genericGuessingPermitted": False,
        "productionActivation": False,
    }
    return validate_requirement(value)


def validate_requirement(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != REQUIREMENT_FIELDS:
        raise FineIdentityApplicationError("fine-identity requirement fields are not canonical")
    if (
        value.get("format") != REQUIREMENT_FORMAT
        or value.get("version") != VERSION
        or value.get("policyRevision") != POLICY_REVISION
        or value.get("sourceGroundedRequired") is not True
        or value.get("applicationRequired") is not True
        or value.get("genericGuessingPermitted") is not False
        or value.get("productionActivation") is not False
    ):
        raise FineIdentityApplicationError("fine-identity requirement authority boundary is invalid")
    _revision(value.get("bodyrigRevision"))
    _sha(value.get("fineIdentityAuthoritySha256"), label="fine-identity authority SHA-256")
    _sha(value.get("fineIdentityAttestationSha256"), label="fine-identity attestation SHA-256")
    return dict(value)


def validate_application(
    value: Mapping[str, Any],
    *,
    requirement: Mapping[str, Any],
    avatar_vrm: bytes,
) -> dict[str, Any]:
    expected_requirement = validate_requirement(requirement)
    if not isinstance(value, Mapping) or set(value) != APPLICATION_FIELDS:
        raise FineIdentityApplicationError("fine-identity application fields are not canonical")
    if (
        value.get("format") != APPLICATION_FORMAT
        or value.get("version") != VERSION
        or value.get("policyRevision") != POLICY_REVISION
        or value.get("sourceGrounded") is not True
        or value.get("generative") is not False
        or value.get("packageApplicationAuthority") is not True
        or value.get("geometryModified") is not True
        or value.get("appearanceModified") is not True
        or value.get("humanReviewRequired") is not True
        or value.get("productionActivation") is not False
    ):
        raise FineIdentityApplicationError("fine-identity application authority boundary is invalid")

    revision = _revision(value.get("bodyrigRevision"))
    authority_sha = _sha(value.get("fineIdentityAuthoritySha256"), label="fine-identity authority SHA-256")
    attestation_sha = _sha(
        value.get("fineIdentityAttestationSha256"),
        label="fine-identity attestation SHA-256",
    )
    if revision != expected_requirement["bodyrigRevision"]:
        raise FineIdentityApplicationError("fine-identity application BodyRig revision mismatch")
    if authority_sha != expected_requirement["fineIdentityAuthoritySha256"]:
        raise FineIdentityApplicationError("fine-identity application authority SHA mismatch")
    if attestation_sha != expected_requirement["fineIdentityAttestationSha256"]:
        raise FineIdentityApplicationError("fine-identity application attestation SHA mismatch")

    domains = value.get("domains")
    if not isinstance(domains, Mapping) or set(domains) != set(REQUIRED_DOMAINS):
        raise FineIdentityApplicationError("fine-identity application domain set is incomplete")
    for domain, minimum in REQUIRED_DOMAINS.items():
        entry = domains.get(domain)
        if not isinstance(entry, Mapping) or set(entry) != DOMAIN_FIELDS:
            raise FineIdentityApplicationError(f"{domain} application fields are not canonical")
        count = entry.get("sourceEvidenceCount")
        if isinstance(count, bool) or not isinstance(count, int) or count < 2:
            raise FineIdentityApplicationError(f"{domain} requires at least two source evidence items")
        if minimum["geometry"] and entry.get("geometryApplied") is not True:
            raise FineIdentityApplicationError(f"{domain} has no geometry application authority")
        if minimum["appearance"] and entry.get("appearanceApplied") is not True:
            raise FineIdentityApplicationError(f"{domain} has no appearance application authority")
        for field in ("geometryApplied", "appearanceApplied"):
            if type(entry.get(field)) is not bool:
                raise FineIdentityApplicationError(f"{domain} {field} is not boolean")

    source_geometry = _sha(
        value.get("sourceGeometrySurfaceSha256"),
        label="fine-identity source geometry SHA-256",
    )
    candidate_geometry = _sha(
        value.get("candidateGeometrySurfaceSha256"),
        label="fine-identity candidate geometry SHA-256",
    )
    source_appearance = _sha(
        value.get("sourceAppearanceGlobalSha256"),
        label="fine-identity source appearance SHA-256",
    )
    candidate_appearance = _sha(
        value.get("candidateAppearanceGlobalSha256"),
        label="fine-identity candidate appearance SHA-256",
    )
    if source_geometry == candidate_geometry:
        raise FineIdentityApplicationError("fine-identity application did not change geometry bytes")
    if source_appearance == candidate_appearance:
        raise FineIdentityApplicationError("fine-identity application did not change appearance bytes")

    try:
        fingerprints = _avatar_fingerprints(avatar_vrm)
    except FidelityAbError as exc:
        raise FineIdentityApplicationError(f"fine-identity candidate avatar fingerprints are invalid: {exc}") from exc
    if fingerprints.get("geometry_surface_sha256") != candidate_geometry:
        raise FineIdentityApplicationError("fine-identity candidate geometry no longer matches current avatar")
    if fingerprints.get("appearance_global_sha256") != candidate_appearance:
        raise FineIdentityApplicationError("fine-identity candidate appearance no longer matches current avatar")
    return dict(value)


def build_application(
    *,
    requirement: Mapping[str, Any],
    attestation: Mapping[str, Any],
    attestation_bytes: bytes,
    source_avatar_vrm: bytes,
    candidate_avatar_vrm: bytes,
    domain_application: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a canonical fine-identity application receipt for already-applied source-derived edits.

    This function certifies an edited candidate; it does not synthesize or infer identity details.
    Domain application booleans are explicit operator/modeling evidence, while source-evidence counts
    are derived from the validated photoidentity attestation.
    """
    expected_requirement = validate_requirement(requirement)
    if hashlib.sha256(attestation_bytes).hexdigest() != expected_requirement["fineIdentityAttestationSha256"]:
        raise FineIdentityApplicationError(
            "fine-identity attestation bytes do not match the exact requirement"
        )
    try:
        validated_attestation = validate_attestation(
            attestation,
            expected_bodyrig_revision=expected_requirement["bodyrigRevision"],
        )
    except PhotoIdentityFineIdentityAttestationError as exc:
        raise FineIdentityApplicationError(str(exc)) from exc

    if not isinstance(domain_application, Mapping) or set(domain_application) != set(REQUIRED_DOMAINS):
        raise FineIdentityApplicationError("fine-identity domain application set is incomplete")

    evidence_scenes: dict[str, set[str]] = {domain: set() for domain in REQUIRED_DOMAINS}
    for item in validated_attestation["selected_evidence"]:
        domain = str(item["domain"])
        evidence_scenes[domain].add(str(item["scene_id"]))

    domains: dict[str, dict[str, Any]] = {}
    for domain, minimum in REQUIRED_DOMAINS.items():
        item = domain_application.get(domain)
        if not isinstance(item, Mapping) or set(item) != {"geometryApplied", "appearanceApplied"}:
            raise FineIdentityApplicationError(
                f"{domain} application declaration fields are not canonical"
            )
        geometry_applied = item.get("geometryApplied")
        appearance_applied = item.get("appearanceApplied")
        if type(geometry_applied) is not bool or type(appearance_applied) is not bool:
            raise FineIdentityApplicationError(f"{domain} application declaration is not boolean")
        if minimum["geometry"] and geometry_applied is not True:
            raise FineIdentityApplicationError(f"{domain} geometry application is not confirmed")
        if minimum["appearance"] and appearance_applied is not True:
            raise FineIdentityApplicationError(f"{domain} appearance application is not confirmed")
        domains[domain] = {
            "sourceEvidenceCount": len(evidence_scenes[domain]),
            "geometryApplied": geometry_applied,
            "appearanceApplied": appearance_applied,
        }

    try:
        source_fp = _avatar_fingerprints(source_avatar_vrm)
        candidate_fp = _avatar_fingerprints(candidate_avatar_vrm)
    except FidelityAbError as exc:
        raise FineIdentityApplicationError(
            f"fine-identity package fingerprints are invalid: {exc}"
        ) from exc

    if source_fp["geometry_surface_sha256"] == candidate_fp["geometry_surface_sha256"]:
        raise FineIdentityApplicationError("fine-identity candidate did not change geometry")
    if source_fp["appearance_global_sha256"] == candidate_fp["appearance_global_sha256"]:
        raise FineIdentityApplicationError("fine-identity candidate did not change appearance")
    if source_fp["rig_sha256"] != candidate_fp["rig_sha256"]:
        raise FineIdentityApplicationError("fine-identity candidate changed protected rig authority")

    value = {
        "format": APPLICATION_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "bodyrigRevision": expected_requirement["bodyrigRevision"],
        "fineIdentityAuthoritySha256": expected_requirement["fineIdentityAuthoritySha256"],
        "fineIdentityAttestationSha256": expected_requirement["fineIdentityAttestationSha256"],
        "domains": domains,
        "sourceGeometrySurfaceSha256": source_fp["geometry_surface_sha256"],
        "candidateGeometrySurfaceSha256": candidate_fp["geometry_surface_sha256"],
        "sourceAppearanceGlobalSha256": source_fp["appearance_global_sha256"],
        "candidateAppearanceGlobalSha256": candidate_fp["appearance_global_sha256"],
        "sourceGrounded": True,
        "generative": False,
        "packageApplicationAuthority": True,
        "geometryModified": True,
        "appearanceModified": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    return validate_application(
        value,
        requirement=expected_requirement,
        avatar_vrm=candidate_avatar_vrm,
    )
