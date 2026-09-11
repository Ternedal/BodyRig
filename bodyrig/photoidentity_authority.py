from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_evidence import PhotoIdentityEvidenceError, validate_bundle

# Central authority table for evidence that may eventually be registered against
# a body-build. Generic evidence helpers intentionally remain usable in tests and
# offline analysis, but registration/status routing must pass this exact table.
COARSE_CAPABILITIES = {"coarse-face-view", "coarse-full-body-view"}
OPENPOSE_CAPABILITIES = {"eyes-detail", "hands-detail", "feet-detail"}
SCHP_CAPABILITIES = {"hair-detail", "skin-detail"}
NAIL_CAPABILITIES = {"fingernails-detail", "toenails-detail"}
ANATOMY_CAPABILITIES = {"rear-body-view", "torso-chest-detail", "waist-hips-detail"}

ANALYZER_AUTHORITY: dict[tuple[str, str], frozenset[str]] = {
    ("opencv-hog-haar", "1"): frozenset(COARSE_CAPABILITIES),
    ("bodyrig-photoidentity-coarse-openpose-composite", "1"): frozenset(
        COARSE_CAPABILITIES | OPENPOSE_CAPABILITIES
    ),
    ("bodyrig-photoidentity-coarse-openpose-schp-composite", "1"): frozenset(
        COARSE_CAPABILITIES | OPENPOSE_CAPABILITIES | SCHP_CAPABILITIES
    ),
    ("bodyrig-photoidentity-coarse-openpose-schp-human-target-detail-composite", "1"): frozenset(
        COARSE_CAPABILITIES | OPENPOSE_CAPABILITIES | SCHP_CAPABILITIES
    ),
    ("bodyrig-photoidentity-coarse-openpose-schp-human-nails-composite", "1"): frozenset(
        COARSE_CAPABILITIES | OPENPOSE_CAPABILITIES | SCHP_CAPABILITIES | NAIL_CAPABILITIES
    ),
    ("bodyrig-photoidentity-source-human-anatomy-composite", "1"): frozenset(
        COARSE_CAPABILITIES
        | OPENPOSE_CAPABILITIES
        | SCHP_CAPABILITIES
        | NAIL_CAPABILITIES
        | ANATOMY_CAPABILITIES
    ),
}

# The tuple remains the canonical single-performer authority and is intentionally
# kept stable because several tests/operators use it to build fixtures. Additional
# authority is opt-in per domain below; it never replaces the original source path.
DETAIL_DOMAIN_AUTHORITY: dict[str, tuple[str, str, str]] = {
    "eyes_detail": ("eyes-detail", "openpose-body25-face-hand-detail", "1"),
    "hands": ("hands-detail", "openpose-body25-face-hand-detail", "1"),
    "feet": ("feet-detail", "openpose-body25-face-hand-detail", "1"),
    "hair_hairline": ("hair-detail", "schp-atr18-source-observability", "1"),
    "skin_detail": ("skin-detail", "schp-atr18-source-observability", "1"),
    "fingernails_detail": ("fingernails-detail", "human-source-nail-detail-attestation", "1"),
    "toenails_detail": ("toenails-detail", "human-source-nail-detail-attestation", "1"),
    "body_rear": ("rear-body-view", "human-source-anatomy-observability-attestation", "1"),
    "torso_chest": ("torso-chest-detail", "human-source-anatomy-observability-attestation", "1"),
    "waist_hips": ("waist-hips-detail", "human-source-anatomy-observability-attestation", "1"),
}

HUMAN_TARGET_DETAIL_AUTHORITY = ("human-reviewed-target-crop-detail-quality", "1")
DETAIL_DOMAIN_ADDITIONAL_AUTHORITIES: dict[str, frozenset[tuple[str, str]]] = {
    "eyes_detail": frozenset({HUMAN_TARGET_DETAIL_AUTHORITY}),
    "hands": frozenset({HUMAN_TARGET_DETAIL_AUTHORITY}),
    "feet": frozenset({HUMAN_TARGET_DETAIL_AUTHORITY}),
    "hair_hairline": frozenset({HUMAN_TARGET_DETAIL_AUTHORITY}),
    "skin_detail": frozenset({HUMAN_TARGET_DETAIL_AUTHORITY}),
}

COARSE_DOMAINS = {
    "face_front",
    "face_left_profile",
    "face_right_profile",
    "body_front",
    "body_left_profile",
    "body_right_profile",
}


class PhotoIdentityAuthorityError(PhotoIdentityEvidenceError):
    pass


def _read_observations(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityAuthorityError("photoidentity authority observations are unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityAuthorityError("photoidentity authority observations must be an object")
    return value


def validate_authoritative_observation_evidence(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise PhotoIdentityAuthorityError("photoidentity authority evidence must be an object")
    analyzer = value.get("analyzer")
    if not isinstance(analyzer, Mapping):
        raise PhotoIdentityAuthorityError("photoidentity authority analyzer block is missing")
    adapter = str(analyzer.get("adapter") or "").strip()
    revision = str(analyzer.get("revision") or "").strip()
    allowed_capabilities = ANALYZER_AUTHORITY.get((adapter, revision))
    if allowed_capabilities is None:
        raise PhotoIdentityAuthorityError(
            f"photoidentity analyzer is not registered authority: {adapter or 'empty'}@{revision or 'empty'}"
        )
    raw_capabilities = analyzer.get("capabilities")
    if not isinstance(raw_capabilities, list):
        raise PhotoIdentityAuthorityError("photoidentity authority capabilities must be a list")
    capabilities = {str(item or "").strip() for item in raw_capabilities}
    if "" in capabilities:
        raise PhotoIdentityAuthorityError("photoidentity authority contains an empty capability")
    unauthorized = sorted(capabilities - set(allowed_capabilities))
    if unauthorized:
        raise PhotoIdentityAuthorityError(
            "photoidentity analyzer claimed capability outside exact adapter authority: " + ", ".join(unauthorized)
        )

    details = value.get("detail_evidence")
    if not isinstance(details, Mapping):
        raise PhotoIdentityAuthorityError("photoidentity authority detail evidence must be an object")
    for domain, raw_claims in details.items():
        domain_name = str(domain)
        if domain_name in COARSE_DOMAINS:
            if raw_claims:
                raise PhotoIdentityAuthorityError(
                    f"coarse photoidentity domain must derive from observation rows, not detail claims: {domain_name}"
                )
            continue
        authority = DETAIL_DOMAIN_AUTHORITY.get(domain_name)
        if authority is None:
            raise PhotoIdentityAuthorityError(f"photoidentity detail domain has no registered authority: {domain_name}")
        capability, claim_adapter, claim_revision = authority
        if capability not in capabilities:
            raise PhotoIdentityAuthorityError(
                f"photoidentity detail claims exist without their exact capability: {domain_name} -> {capability}"
            )
        if not isinstance(raw_claims, list):
            raise PhotoIdentityAuthorityError(f"photoidentity detail claims are not a list: {domain_name}")
        allowed_claim_authorities = {
            (claim_adapter, claim_revision),
            *DETAIL_DOMAIN_ADDITIONAL_AUTHORITIES.get(domain_name, frozenset()),
        }
        for raw in raw_claims:
            if not isinstance(raw, Mapping):
                raise PhotoIdentityAuthorityError(f"photoidentity detail claim is invalid: {domain_name}")
            if raw.get("source_derived") is not True:
                raise PhotoIdentityAuthorityError(f"photoidentity detail claim is not source-derived: {domain_name}")
            actual_adapter = str(raw.get("adapter") or "")
            actual_revision = str(raw.get("revision") or "")
            if (actual_adapter, actual_revision) not in allowed_claim_authorities:
                allowed = ", ".join(f"{item[0]}@{item[1]}" for item in sorted(allowed_claim_authorities))
                raise PhotoIdentityAuthorityError(
                    f"photoidentity detail claim does not match registered domain authority: "
                    f"{domain_name} allows {allowed}, got {actual_adapter or 'empty'}@{actual_revision or 'empty'}"
                )
    return dict(value)


def validate_authoritative_bundle(
    report_path: str | Path,
    observation_path: str | Path | None = None,
    *,
    require_sufficient: bool = False,
    expected_performer_id: str | None = None,
    expected_bodyrig_revision: str | None = None,
    expected_baseline_source_manifest_sha256: str | None = None,
) -> dict[str, Any]:
    report_file = Path(report_path).expanduser().resolve()
    observations_file = (
        Path(observation_path).expanduser().resolve()
        if observation_path is not None
        else report_file.with_name("photoidentity-observations.json")
    )
    # First preserve the canonical structural/hash/sufficiency validation.
    report = validate_bundle(
        report_file,
        observations_file,
        require_sufficient=require_sufficient,
        expected_performer_id=expected_performer_id,
        expected_bodyrig_revision=expected_bodyrig_revision,
        expected_baseline_source_manifest_sha256=expected_baseline_source_manifest_sha256,
    )
    observations = _read_observations(observations_file)
    validate_authoritative_observation_evidence(observations)
    return report
