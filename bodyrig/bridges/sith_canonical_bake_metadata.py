from __future__ import annotations

import math
from typing import Any, Mapping

from sith_pbr_material import PbrMaterialError, _read_glb, _write_glb


METHOD = "canonical-smplx-closest-surface-bake-v1"
LEGACY_METHOD = "sith-source-local-triangle-barycentric-uv-v1"


class CanonicalBakeMetadataError(ValueError):
    pass


def _finite_nonnegative(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CanonicalBakeMetadataError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        raise CanonicalBakeMetadataError(f"{label} is invalid")
    return result


def _sha256(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise CanonicalBakeMetadataError(f"{label} is invalid")
    digest = value.strip().lower()
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise CanonicalBakeMetadataError(f"{label} is invalid")
    return digest


def _positive_integer(value: Any, *, label: str) -> int:
    number = _finite_nonnegative(value, label=label)
    integer = int(number)
    if integer < 1 or abs(number - integer) > 1e-9:
        raise CanonicalBakeMetadataError(f"{label} is invalid")
    return integer


def canonical_appearance_transfer(
    bodyrig: Mapping[str, Any],
    mapping_metrics: Mapping[str, float | str],
) -> dict[str, Any]:
    """Build truthful R7 appearance authority from a completed legacy donor receipt.

    The legacy donor metadata step remains responsible for geometry/LBS authority
    and for validating the source-derived PBR/base-color refinement receipts. R7
    replaces only appearanceTransfer after proving that the refinement source is
    byte-identical to the canonical baked PNG.
    """

    legacy = bodyrig.get("appearanceTransfer")
    if not isinstance(legacy, dict) or legacy.get("method") != LEGACY_METHOD:
        raise CanonicalBakeMetadataError("legacy donor appearance receipt is missing")
    geometry = bodyrig.get("geometryAuthority")
    if geometry != {
        "method": "smplx-fitted-donor-topology-v1",
        "sourceMeshGeometryUsed": False,
        "stableTopology": True,
    }:
        raise CanonicalBakeMetadataError("SMPL-X donor geometry authority is invalid")

    internal_method = mapping_metrics.get("appearance_method")
    if internal_method != "canonical-surface-bake-v1":
        raise CanonicalBakeMetadataError("canonical texture bake method is invalid")

    canonical_uv_sha = _sha256(
        mapping_metrics.get("canonical_uv_template_sha256"),
        label="canonical SMPL-X UV template SHA-256",
    )
    source_texture_sha = _sha256(
        mapping_metrics.get("source_texture_sha256"),
        label="SiTH reconstruction texture SHA-256",
    )
    baked_sha = _sha256(
        mapping_metrics.get("baked_basecolor_sha256"),
        label="canonical baked base-color SHA-256",
    )
    refinement_source_sha = _sha256(
        legacy.get("sourceBaseColorSha256"),
        label="refinement source base-color SHA-256",
    )
    active_sha = _sha256(
        legacy.get("activeBaseColorSha256"),
        label="active base-color SHA-256",
    )
    if baked_sha != refinement_source_sha:
        raise CanonicalBakeMetadataError(
            "canonical baked base-color is not the byte authority consumed by refinement"
        )

    width = _positive_integer(mapping_metrics.get("bake_width"), label="canonical bake width")
    height = _positive_integer(mapping_metrics.get("bake_height"), label="canonical bake height")
    occupied_count = _positive_integer(
        mapping_metrics.get("bake_occupied_texel_count"),
        label="canonical bake occupied texel count",
    )
    gutter = _finite_nonnegative(
        mapping_metrics.get("bake_gutter_pixels"),
        label="canonical bake gutter pixels",
    )
    if abs(gutter - int(gutter)) > 1e-9 or gutter > 64:
        raise CanonicalBakeMetadataError("canonical bake gutter pixels is invalid")
    occupied_ratio = _finite_nonnegative(
        mapping_metrics.get("bake_occupied_ratio"),
        label="canonical bake occupied ratio",
    )
    padded_ratio = _finite_nonnegative(
        mapping_metrics.get("bake_padded_texel_ratio"),
        label="canonical bake padded ratio",
    )
    if occupied_ratio > 1.0 or padded_ratio > 1.0 or padded_ratio + 1e-9 < occupied_ratio:
        raise CanonicalBakeMetadataError("canonical bake coverage ratio is invalid")
    if occupied_count > width * height:
        raise CanonicalBakeMetadataError("canonical bake occupied texel count exceeds atlas size")

    surface_p95 = _finite_nonnegative(
        mapping_metrics.get("bake_surface_distance_p95"),
        label="canonical bake surface distance p95",
    )
    surface_max = _finite_nonnegative(
        mapping_metrics.get("bake_surface_distance_max"),
        label="canonical bake surface distance max",
    )
    if surface_p95 > surface_max + 1e-9:
        raise CanonicalBakeMetadataError("canonical bake surface distance ordering is invalid")

    pbr_method = legacy.get("pbrRefinementMethod")
    basecolor_method = legacy.get("baseColorRefinementMethod")
    if not isinstance(pbr_method, str) or not pbr_method.strip():
        raise CanonicalBakeMetadataError("source-derived PBR method is invalid")
    if not isinstance(basecolor_method, str) or not basecolor_method.strip():
        raise CanonicalBakeMetadataError("bounded base-color refinement method is invalid")
    if legacy.get("sourceDerivedPbrApplied") is not True:
        raise CanonicalBakeMetadataError("source-derived PBR authority is invalid")
    if legacy.get("boundedBaseColorRefinementApplied") is not True:
        raise CanonicalBakeMetadataError("bounded base-color refinement authority is invalid")

    return {
        "method": METHOD,
        "canonicalDonorAtlas": True,
        "canonicalUvTemplateSha256": canonical_uv_sha,
        "sourceReconstructionTextureSha256": source_texture_sha,
        "bakedBaseColorSha256": baked_sha,
        "activeBaseColorSha256": active_sha,
        "bakeWidth": width,
        "bakeHeight": height,
        "occupiedTexelCount": occupied_count,
        "occupiedTexelRatio": round(occupied_ratio, 6),
        "paddedTexelRatio": round(padded_ratio, 6),
        "gutterPixels": int(gutter),
        "nearestSourceSurfaceDistanceP95": round(surface_p95, 6),
        "nearestSourceSurfaceDistanceMax": round(surface_max, 6),
        "sourceTextureBytesPreservedAsSeparateAuthority": True,
        "activeBaseColorUsesExactSourceBytes": False,
        "bakedBaseColorConsumedByRefinement": True,
        "sourceDerivedPbrApplied": True,
        "boundedBaseColorRefinementApplied": True,
        "generativeAppearanceSynthesis": False,
        "pbrRefinementMethod": pbr_method.strip(),
        "baseColorRefinementMethod": basecolor_method.strip(),
        "baseColorMaxObservedChannelDelta": legacy.get("baseColorMaxObservedChannelDelta"),
        "baseColorChannelDeltaCap": legacy.get("baseColorChannelDeltaCap"),
        "geometryModified": False,
    }


def replace_with_canonical_bake_metadata(
    avatar_vrm: bytes,
    *,
    mapping_metrics: Mapping[str, float | str],
) -> bytes:
    try:
        document, binary = _read_glb(avatar_vrm)
    except PbrMaterialError as exc:
        raise CanonicalBakeMetadataError(str(exc)) from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise CanonicalBakeMetadataError("BodyRig VRM metadata is missing")
    bodyrig["appearanceTransfer"] = canonical_appearance_transfer(bodyrig, mapping_metrics)
    return _write_glb(document, binary)
