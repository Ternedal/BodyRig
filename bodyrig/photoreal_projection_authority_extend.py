from __future__ import annotations

import copy
from typing import Any, Mapping

from .photoreal_explicit_projection_authority import (
    MANIFEST_FORMAT,
    MANIFEST_VERSION,
    PhotorealExplicitProjectionAuthorityError,
    apply_explicit_projection_authority,
)
from .photoreal_explicit_projection_authority_cli import (
    PhotorealExplicitProjectionAuthorityCliError,
    _receipt_sha_index,
    _spatial_source_keys,
    _vr180_equi_authority,
)

KNOWN_STEREO_LAYOUTS = {"side-by-side", "over-under", "mono"}


class PhotorealProjectionAuthorityExtensionError(ValueError):
    pass


def _validate_prior_manifest(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    prior_manifest: Mapping[str, Any],
) -> tuple[str, set[str]]:
    performer_id, spatial_keys = _spatial_source_keys(plan)
    spatial_set = set(spatial_keys)

    if prior_manifest.get("format") != MANIFEST_FORMAT or prior_manifest.get("version") != MANIFEST_VERSION:
        raise PhotorealProjectionAuthorityExtensionError("prior projection authority format/version mismatch")
    if str(prior_manifest.get("performer_id") or "").strip() != performer_id:
        raise PhotorealProjectionAuthorityExtensionError("prior projection authority performer mismatch")
    if prior_manifest.get("build_only") is not True or prior_manifest.get("runtime_dependency") is not False:
        raise PhotorealProjectionAuthorityExtensionError("prior projection authority boundary is invalid")
    if prior_manifest.get("production_activation") is not False:
        raise PhotorealProjectionAuthorityExtensionError("prior projection authority crossed production authority")

    raw_sources = prior_manifest.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise PhotorealProjectionAuthorityExtensionError("prior projection authority contains no sources")

    prior_keys: set[str] = set()
    for raw in raw_sources:
        if not isinstance(raw, Mapping):
            raise PhotorealProjectionAuthorityExtensionError("prior projection authority source is invalid")
        key = str(raw.get("source_key") or "").strip()
        if not key:
            raise PhotorealProjectionAuthorityExtensionError("prior projection authority source key is invalid")
        if key in prior_keys:
            raise PhotorealProjectionAuthorityExtensionError("prior projection authority repeats a source key")
        prior_keys.add(key)

    outside = sorted(prior_keys - spatial_set)
    if outside:
        raise PhotorealProjectionAuthorityExtensionError(
            f"prior projection authority references {len(outside)} source(s) no longer classified as spatial"
        )

    try:
        _resolved, consumed = apply_explicit_projection_authority(plan, receipt, prior_manifest)
    except PhotorealExplicitProjectionAuthorityError as exc:
        raise PhotorealProjectionAuthorityExtensionError(
            f"prior projection authority no longer validates against the new receipt: {exc}"
        ) from exc
    if consumed != len(prior_keys):
        raise PhotorealProjectionAuthorityExtensionError(
            "prior projection authority preflight did not consume its complete source universe"
        )
    return performer_id, prior_keys


def extend_verified_vr180_manifest(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    prior_manifest: Mapping[str, Any],
    *,
    new_stereo_layout: str,
    operator_verified_new_sources: bool,
) -> tuple[dict[str, Any], list[str]]:
    if new_stereo_layout not in KNOWN_STEREO_LAYOUTS:
        raise PhotorealProjectionAuthorityExtensionError("new-source stereo layout is unsupported")

    performer_id, prior_keys = _validate_prior_manifest(plan, receipt, prior_manifest)
    _performer_check, spatial_keys = _spatial_source_keys(plan)
    spatial_set = set(spatial_keys)
    missing = sorted(spatial_set - prior_keys)
    if not missing:
        raise PhotorealProjectionAuthorityExtensionError(
            "new dataset plan adds no spatial sources beyond the prior projection authority"
        )
    if operator_verified_new_sources is not True:
        raise PhotorealProjectionAuthorityExtensionError(
            "projection authority extension requires explicit operator verification of every newly spatial source"
        )

    receipt_sha = _receipt_sha_index(receipt, performer_id=performer_id)
    unbound = [key for key in missing if key not in receipt_sha]
    if unbound:
        raise PhotorealProjectionAuthorityExtensionError(
            f"new source receipt does not SHA-bind every newly spatial source ({len(unbound)} missing)"
        )

    authority = _vr180_equi_authority()
    combined = copy.deepcopy(dict(prior_manifest))
    combined_sources = [copy.deepcopy(dict(item)) for item in prior_manifest["sources"]]
    combined_sources.extend(
        {
            "source_key": key,
            "source_sha256": receipt_sha[key],
            "stereo_layout": new_stereo_layout,
            "authority_basis": "operator-verified",
            "projection_authority": copy.deepcopy(authority),
        }
        for key in missing
    )
    combined_sources.sort(key=lambda item: str(item["source_key"]).casefold())
    combined["sources"] = combined_sources

    try:
        _resolved, consumed = apply_explicit_projection_authority(plan, receipt, combined)
    except PhotorealExplicitProjectionAuthorityError as exc:
        raise PhotorealProjectionAuthorityExtensionError(
            f"extended projection authority preflight failed: {exc}"
        ) from exc
    if consumed != len(spatial_set) or len(combined_sources) != len(spatial_set):
        raise PhotorealProjectionAuthorityExtensionError(
            "extended projection authority does not exactly cover the new spatial source universe"
        )
    return combined, missing
