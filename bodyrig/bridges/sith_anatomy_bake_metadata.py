from __future__ import annotations

import math
from typing import Any, Mapping

from sith_canonical_bake_metadata import (
    CanonicalBakeMetadataError,
    canonical_appearance_transfer,
)
from sith_pbr_material import PbrMaterialError, _read_glb, _write_glb


METHOD = "canonical-smplx-anatomy-normal-bake-v2"
INTERNAL_METHOD = "canonical-anatomy-normal-bake-v2"


class AnatomyBakeMetadataError(ValueError):
    pass


def _finite_nonnegative(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnatomyBakeMetadataError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise AnatomyBakeMetadataError(f"{label} is invalid")
    return result


def _finite_signed(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnatomyBakeMetadataError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise AnatomyBakeMetadataError(f"{label} is invalid")
    return result


def _ratio(value: Any, *, label: str) -> float:
    result = _finite_nonnegative(value, label=label)
    if result > 1.0:
        raise AnatomyBakeMetadataError(f"{label} is invalid")
    return result


def anatomy_appearance_transfer(
    bodyrig: Mapping[str, Any],
    mapping_metrics: Mapping[str, float | str],
) -> dict[str, Any]:
    if mapping_metrics.get("appearance_method") != INTERNAL_METHOD:
        raise AnatomyBakeMetadataError("anatomy-aware texture bake method is invalid")

    compatibility = dict(mapping_metrics)
    compatibility["appearance_method"] = "canonical-surface-bake-v1"
    try:
        receipt = canonical_appearance_transfer(bodyrig, compatibility)
    except CanonicalBakeMetadataError as exc:
        raise AnatomyBakeMetadataError(str(exc)) from exc

    region_count = _finite_nonnegative(
        mapping_metrics.get("anatomy_region_count"),
        label="anatomy region count",
    )
    if abs(region_count - 6.0) > 1e-9:
        raise AnatomyBakeMetadataError("anatomy region count is invalid")
    restricted_ratio = _ratio(
        mapping_metrics.get("anatomy_restricted_texel_ratio"),
        label="anatomy restricted texel ratio",
    )
    if abs(restricted_ratio - 1.0) > 1e-9:
        raise AnatomyBakeMetadataError("anatomy restriction does not cover every baked texel")
    retry_count = _finite_nonnegative(
        mapping_metrics.get("normal_retry_texel_count"),
        label="normal retry texel count",
    )
    retry_ratio = _ratio(
        mapping_metrics.get("normal_retry_texel_ratio"),
        label="normal retry texel ratio",
    )
    alignment_mean = _finite_signed(
        mapping_metrics.get("normal_alignment_mean"),
        label="normal alignment mean",
    )
    alignment_p05 = _finite_signed(
        mapping_metrics.get("normal_alignment_p05"),
        label="normal alignment p05",
    )
    if not -1.0 <= alignment_mean <= 1.0:
        raise AnatomyBakeMetadataError("normal alignment mean is invalid")
    if not -1.0 <= alignment_p05 <= 1.0:
        raise AnatomyBakeMetadataError("normal alignment p05 is invalid")
    low_alignment_ratio = _ratio(
        mapping_metrics.get("normal_low_alignment_ratio"),
        label="normal low-alignment ratio",
    )
    body_scale = _finite_nonnegative(mapping_metrics.get("body_scale"), label="body scale")
    if body_scale <= 1e-6:
        raise AnatomyBakeMetadataError("body scale is invalid")

    region_ratios: dict[str, float] = {}
    for region in ("torso", "head", "left_arm", "right_arm", "left_leg", "right_leg"):
        region_ratios[region] = _ratio(
            mapping_metrics.get(f"region_{region}_texel_ratio"),
            label=f"{region} texel ratio",
        )
    if abs(sum(region_ratios.values()) - 1.0) > 1e-4:
        raise AnatomyBakeMetadataError("anatomy texel region ratios do not cover the atlas")

    receipt.update(
        {
            "method": METHOD,
            "anatomyRestrictedSourceSearch": True,
            "anatomyRegionCount": 6,
            "anatomyRestrictedTexelRatio": round(restricted_ratio, 6),
            "normalAwareFallback": True,
            "normalRetryTexelCount": int(retry_count),
            "normalRetryTexelRatio": round(retry_ratio, 6),
            "normalAlignmentMean": round(alignment_mean, 6),
            "normalAlignmentP05": round(alignment_p05, 6),
            "normalLowAlignmentRatio": round(low_alignment_ratio, 6),
            "bodyScale": round(body_scale, 6),
            "anatomyTexelRatios": {key: round(value, 6) for key, value in region_ratios.items()},
            "sourceCandidateSearchGlobal": False,
            "geometryModified": False,
        }
    )
    return receipt


def replace_with_anatomy_bake_metadata(
    avatar_vrm: bytes,
    *,
    mapping_metrics: Mapping[str, float | str],
) -> bytes:
    try:
        document, binary = _read_glb(avatar_vrm)
    except PbrMaterialError as exc:
        raise AnatomyBakeMetadataError(str(exc)) from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise AnatomyBakeMetadataError("BodyRig VRM metadata is missing")
    bodyrig["appearanceTransfer"] = anatomy_appearance_transfer(bodyrig, mapping_metrics)
    return _write_glb(document, binary)
