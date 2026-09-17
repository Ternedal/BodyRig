from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_projection_authority import resolve_v2_projection_ambiguity
from .photoreal_spatial_metadata_probe import PhotorealSpatialMetadataProbeError, probe_isobmff_file

PLAN_FORMAT = "bodyrig-photoreal-dataset-plan"
PLAN_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-source-receipt"
RECEIPT_VERSION = 1
MANIFEST_FORMAT = "bodyrig-photoreal-explicit-projection-authority"
MANIFEST_VERSION = 1
PROJECTION_AUTHORITY_FORMAT = "bodyrig-spherical-v2-projection-authority"
PROJECTION_AUTHORITY_VERSION = 1
SPATIAL_HINT_PROJECTIONS = {"projection-ambiguous-2to1", "vr180", "vr360", "equirectangular"}
KNOWN_STEREO_LAYOUTS = {"mono", "side-by-side", "over-under"}
V2_STEREO_TO_LAYOUT = {"mono": "mono", "left-right": "side-by-side", "top-bottom": "over-under"}
_AUTHORITY_FIELDS = {
    "format",
    "version",
    "projection_type",
    "pose_degrees",
    "equirectangular_bounds_fraction",
    "cubemap_layout",
    "cubemap_padding_pixels",
    "mesh_projection_crc32",
    "mesh_projection_encoding",
    "mesh_projection_payload_bytes",
    "mesh_projection_geometry_sha256",
    "mesh_projection_mesh_count",
    "mesh_projection_total_vertex_count",
    "mesh_projection_total_index_count",
    "mesh_projection_texture_ids",
    "mesh_projection_index_types",
    "mesh_projection_unknown_box_types",
    "deprojection_authority",
}
_MANIFEST_FIELDS = {
    "format",
    "version",
    "performer_id",
    "sources",
    "build_only",
    "runtime_dependency",
    "production_activation",
}
_SOURCE_FIELDS = {
    "source_key",
    "source_sha256",
    "stereo_layout",
    "authority_basis",
    "projection_authority",
}


class PhotorealExplicitProjectionAuthorityError(ValueError):
    pass


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealExplicitProjectionAuthorityError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealExplicitProjectionAuthorityError(f"{label} is invalid")
    return result


def _number(value: Any, *, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise PhotorealExplicitProjectionAuthorityError(f"{label} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealExplicitProjectionAuthorityError(f"{label} is invalid") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise PhotorealExplicitProjectionAuthorityError(f"{label} is outside its valid range")
    return result


def _receipt_sources(receipt: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    version = receipt.get("version")
    if receipt.get("format") != RECEIPT_FORMAT or isinstance(version, bool) or version != RECEIPT_VERSION:
        raise PhotorealExplicitProjectionAuthorityError("photoreal source receipt format/version mismatch")
    if receipt.get("all_sources_readable") is not True or receipt.get("all_sources_sha256_bound") is not True:
        raise PhotorealExplicitProjectionAuthorityError("photoreal source receipt is incomplete")
    if receipt.get("source_keys_path_specific") is not True:
        raise PhotorealExplicitProjectionAuthorityError("photoreal source receipt lacks path-specific source keys")
    if receipt.get("build_only") is not True or receipt.get("runtime_dependency") is not False:
        raise PhotorealExplicitProjectionAuthorityError("photoreal source receipt authority boundary is invalid")
    if receipt.get("production_activation") is not False:
        raise PhotorealExplicitProjectionAuthorityError("photoreal source receipt crossed production authority")
    values = receipt.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealExplicitProjectionAuthorityError("photoreal source receipt contains no sources")
    result: dict[str, dict[str, str]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealExplicitProjectionAuthorityError("photoreal source receipt source is invalid")
        source_key = _text(raw.get("source_key"), label="receipt source key")
        if source_key in result:
            raise PhotorealExplicitProjectionAuthorityError("photoreal source receipt repeats a source key")
        result[source_key] = {
            "kind": _text(raw.get("kind"), label="receipt source kind", maximum=16),
            "sha256": _sha(raw.get("sha256"), label="receipt source SHA-256"),
            "resolved_path": _text(raw.get("resolved_path"), label="receipt resolved path", maximum=32768),
        }
    return result


def _validated_equi_authority(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _AUTHORITY_FIELDS:
        raise PhotorealExplicitProjectionAuthorityError(
            "explicit projection authority fields must match the exact v1 geometry schema"
        )
    version = value.get("version")
    if (
        value.get("format") != PROJECTION_AUTHORITY_FORMAT
        or isinstance(version, bool)
        or version != PROJECTION_AUTHORITY_VERSION
    ):
        raise PhotorealExplicitProjectionAuthorityError("explicit projection geometry format/version mismatch")
    if value.get("projection_type") != "equi":
        raise PhotorealExplicitProjectionAuthorityError(
            "explicit projection fallback currently accepts only verified equirectangular geometry"
        )
    if value.get("deprojection_authority") is not False:
        raise PhotorealExplicitProjectionAuthorityError("explicit projection authority crossed deprojection authority")

    pose_value = value.get("pose_degrees")
    if not isinstance(pose_value, Mapping) or set(pose_value) != {"yaw", "pitch", "roll"}:
        raise PhotorealExplicitProjectionAuthorityError("explicit equirectangular pose is invalid")
    pose = {
        "yaw": _number(pose_value.get("yaw"), label="explicit projection yaw", minimum=-180.0, maximum=180.0),
        "pitch": _number(pose_value.get("pitch"), label="explicit projection pitch", minimum=-90.0, maximum=90.0),
        "roll": _number(value=pose_value.get("roll"), label="explicit projection roll", minimum=-180.0, maximum=180.0),
    }

    bounds_value = value.get("equirectangular_bounds_fraction")
    if not isinstance(bounds_value, Mapping) or set(bounds_value) != {"top", "bottom", "left", "right"}:
        raise PhotorealExplicitProjectionAuthorityError("explicit equirectangular bounds are invalid")
    bounds = {
        name: _number(bounds_value.get(name), label=f"explicit equirectangular {name} bound", minimum=0.0, maximum=1.0)
        for name in ("top", "bottom", "left", "right")
    }
    if bounds["top"] + bounds["bottom"] >= 1.0:
        raise PhotorealExplicitProjectionAuthorityError("explicit vertical equirectangular bounds are empty")
    if bounds["left"] + bounds["right"] >= 1.0:
        raise PhotorealExplicitProjectionAuthorityError("explicit horizontal equirectangular bounds are empty")

    nullable_fields = _AUTHORITY_FIELDS - {
        "format",
        "version",
        "projection_type",
        "pose_degrees",
        "equirectangular_bounds_fraction",
        "deprojection_authority",
    }
    if any(value.get(name) is not None for name in nullable_fields):
        raise PhotorealExplicitProjectionAuthorityError(
            "explicit equirectangular authority contains non-equirectangular geometry"
        )

    result = copy.deepcopy(dict(value))
    result["pose_degrees"] = {name: round(number, 6) for name, number in pose.items()}
    result["equirectangular_bounds_fraction"] = {name: round(number, 9) for name, number in bounds.items()}
    return result


def _prove_no_embedded_projection(path: str | Path, *, stereo_layout: str) -> None:
    try:
        probe = probe_isobmff_file(path)
    except (OSError, PhotorealSpatialMetadataProbeError) as exc:
        raise PhotorealExplicitProjectionAuthorityError(
            "explicit projection fallback requires a readable ISO BMFF probe proving embedded authority is absent"
        ) from exc
    if probe.get("probe_status") != "parsed-isobmff":
        raise PhotorealExplicitProjectionAuthorityError(
            "explicit projection fallback requires a parsed ISO BMFF container"
        )
    if probe.get("sv3d_present") is True or probe.get("proj_present") is True or probe.get("spherical_v1_present") is True:
        raise PhotorealExplicitProjectionAuthorityError(
            "explicit projection fallback cannot override embedded spherical projection metadata"
        )
    if probe.get("st3d_present") is True:
        if probe.get("st3d_version") != 0 or probe.get("st3d_flags") != 0:
            raise PhotorealExplicitProjectionAuthorityError(
                "explicit projection fallback found unsupported embedded stereo metadata"
            )
        observed = V2_STEREO_TO_LAYOUT.get(str(probe.get("stereo_mode") or "").strip())
        if observed is None or observed != stereo_layout:
            raise PhotorealExplicitProjectionAuthorityError(
                "explicit stereo layout conflicts with embedded stereo metadata"
            )


def apply_explicit_projection_authority(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    manifest: Mapping[str, Any],
) -> tuple[dict[str, Any], int]:
    plan_version = plan.get("version")
    if plan.get("format") != PLAN_FORMAT or isinstance(plan_version, bool) or plan_version != PLAN_VERSION:
        raise PhotorealExplicitProjectionAuthorityError("photoreal dataset plan format/version mismatch")
    performer_id = _text(plan.get("performer_id"), label="dataset performer id", maximum=256)
    if performer_id != _text(receipt.get("performer_id"), label="receipt performer id", maximum=256):
        raise PhotorealExplicitProjectionAuthorityError("dataset plan/source receipt performer mismatch")

    if not isinstance(manifest, Mapping) or set(manifest) != _MANIFEST_FIELDS:
        raise PhotorealExplicitProjectionAuthorityError("explicit projection manifest fields must match v1 exactly")
    manifest_version = manifest.get("version")
    if (
        manifest.get("format") != MANIFEST_FORMAT
        or isinstance(manifest_version, bool)
        or manifest_version != MANIFEST_VERSION
    ):
        raise PhotorealExplicitProjectionAuthorityError("explicit projection manifest format/version mismatch")
    if _text(manifest.get("performer_id"), label="explicit authority performer id", maximum=256) != performer_id:
        raise PhotorealExplicitProjectionAuthorityError("explicit projection authority performer mismatch")
    if manifest.get("build_only") is not True or manifest.get("runtime_dependency") is not False:
        raise PhotorealExplicitProjectionAuthorityError("explicit projection authority boundary is invalid")
    if manifest.get("production_activation") is not False:
        raise PhotorealExplicitProjectionAuthorityError("explicit projection authority crossed production authority")

    receipt_sources = _receipt_sources(receipt)
    raw_sources = manifest.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise PhotorealExplicitProjectionAuthorityError("explicit projection authority contains no sources")

    entries: dict[str, dict[str, Any]] = {}
    for raw in raw_sources:
        if not isinstance(raw, Mapping) or set(raw) != _SOURCE_FIELDS:
            raise PhotorealExplicitProjectionAuthorityError("explicit projection source fields must match v1 exactly")
        source_key = _text(raw.get("source_key"), label="explicit projection source key")
        if source_key in entries:
            raise PhotorealExplicitProjectionAuthorityError("explicit projection authority repeats a source key")
        source_sha = _sha(raw.get("source_sha256"), label="explicit projection source SHA-256")
        stereo_layout = _text(raw.get("stereo_layout"), label="explicit stereo layout", maximum=128)
        if stereo_layout not in KNOWN_STEREO_LAYOUTS:
            raise PhotorealExplicitProjectionAuthorityError("explicit stereo layout is unsupported")
        if raw.get("authority_basis") != "operator-verified":
            raise PhotorealExplicitProjectionAuthorityError(
                "explicit projection source requires authority_basis=operator-verified"
            )
        projection_authority = _validated_equi_authority(raw.get("projection_authority"))
        verified = receipt_sources.get(source_key)
        if verified is None:
            raise PhotorealExplicitProjectionAuthorityError(
                "explicit projection authority references a source outside the byte receipt"
            )
        if verified["sha256"] != source_sha:
            raise PhotorealExplicitProjectionAuthorityError(
                "explicit projection authority SHA-256 does not match the byte receipt"
            )
        if verified["kind"] != "video":
            raise PhotorealExplicitProjectionAuthorityError("explicit projection authority can bind only video sources")
        entries[source_key] = {
            "stereo_layout": stereo_layout,
            "projection_authority": projection_authority,
            "resolved_path": verified["resolved_path"],
        }

    result = copy.deepcopy(dict(plan))
    consumed: set[str] = set()
    for split in ("train", "evaluation"):
        values = result.get(split)
        if not isinstance(values, list) or not values:
            raise PhotorealExplicitProjectionAuthorityError(f"photoreal dataset plan has no {split} sources")
        for raw in values:
            if not isinstance(raw, dict):
                raise PhotorealExplicitProjectionAuthorityError("photoreal dataset plan source is invalid")
            source_key = _text(raw.get("source_id"), label="dataset source key")
            entry = entries.get(source_key)
            if entry is None:
                continue
            if _text(raw.get("kind"), label="dataset source kind", maximum=16) != "video":
                raise PhotorealExplicitProjectionAuthorityError("explicit projection authority targeted a non-video plan source")
            projection_hint = _text(raw.get("projection"), label="dataset source projection", maximum=128)
            if projection_hint not in SPATIAL_HINT_PROJECTIONS:
                raise PhotorealExplicitProjectionAuthorityError(
                    "explicit projection authority cannot override a non-spatial or already-exact plan projection"
                )
            _prove_no_embedded_projection(entry["resolved_path"], stereo_layout=entry["stereo_layout"])
            raw["projection"] = "equi"
            raw["stereo_layout"] = entry["stereo_layout"]
            raw["projection_authority"] = copy.deepcopy(entry["projection_authority"])
            consumed.add(source_key)

    if consumed != set(entries):
        raise PhotorealExplicitProjectionAuthorityError(
            "explicit projection authority source universe does not match spatial dataset sources"
        )
    return result, len(consumed)


def resolve_projection_authority(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    explicit_manifest: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], int, int]:
    prepared = copy.deepcopy(dict(plan))
    explicit_count = 0
    if explicit_manifest is not None:
        prepared, explicit_count = apply_explicit_projection_authority(prepared, receipt, explicit_manifest)
    resolved, v2_count = resolve_v2_projection_ambiguity(prepared, receipt)
    return resolved, v2_count, explicit_count
