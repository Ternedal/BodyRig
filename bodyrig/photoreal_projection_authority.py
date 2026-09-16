from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from .photoreal_spatial_metadata_probe import PhotorealSpatialMetadataProbeError, probe_isobmff_file

PLAN_FORMAT = "bodyrig-photoreal-dataset-plan"
PLAN_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-source-receipt"
RECEIPT_VERSION = 1
AMBIGUOUS_PROJECTION = "projection-ambiguous-2to1"
V2_PROJECTION_TYPES = {"equi", "mshp", "cbmp"}
KNOWN_STEREO_LAYOUTS = {"mono", "side-by-side", "over-under"}
V2_STEREO_TO_LAYOUT = {"mono": "mono", "left-right": "side-by-side", "top-bottom": "over-under"}


class PhotorealProjectionAuthorityError(ValueError):
    pass


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealProjectionAuthorityError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealProjectionAuthorityError(f"{label} is invalid")
    return result


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PhotorealProjectionAuthorityError(f"{label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealProjectionAuthorityError(f"{label} is invalid") from exc
    if result < 1:
        raise PhotorealProjectionAuthorityError(f"{label} must be positive")
    return result


def _receipt_sources(receipt: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    version = receipt.get("version")
    if receipt.get("format") != RECEIPT_FORMAT or isinstance(version, bool) or version != RECEIPT_VERSION:
        raise PhotorealProjectionAuthorityError("photoreal source receipt format/version mismatch")
    if receipt.get("all_sources_readable") is not True or receipt.get("all_sources_sha256_bound") is not True:
        raise PhotorealProjectionAuthorityError("photoreal source receipt is incomplete")
    if receipt.get("source_keys_path_specific") is not True:
        raise PhotorealProjectionAuthorityError("photoreal source receipt lacks path-specific source keys")
    if receipt.get("build_only") is not True or receipt.get("runtime_dependency") is not False:
        raise PhotorealProjectionAuthorityError("photoreal source receipt authority boundary is invalid")
    if receipt.get("production_activation") is not False:
        raise PhotorealProjectionAuthorityError("photoreal source receipt crossed production authority")
    values = receipt.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealProjectionAuthorityError("photoreal source receipt contains no sources")
    result: dict[str, dict[str, str]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealProjectionAuthorityError("photoreal source receipt source is invalid")
        source_key = _text(raw.get("source_key"), label="receipt source key")
        if source_key in result:
            raise PhotorealProjectionAuthorityError("photoreal source receipt repeats a source key")
        result[source_key] = {
            "kind": _text(raw.get("kind"), label="receipt source kind", maximum=16),
            "sha256": _sha(raw.get("sha256"), label="receipt source SHA-256"),
            "resolved_path": _text(raw.get("resolved_path"), label="receipt resolved path", maximum=32768),
        }
    return result


def _probe_v2_projection(path: str | Path) -> dict[str, Any]:
    try:
        probe = probe_isobmff_file(path)
    except (OSError, PhotorealSpatialMetadataProbeError) as exc:
        raise PhotorealProjectionAuthorityError(
            "ambiguous projection source has no readable authoritative Spherical V2 metadata"
        ) from exc
    if probe.get("probe_status") != "parsed-isobmff":
        raise PhotorealProjectionAuthorityError("ambiguous projection source is not a parsed ISO BMFF container")
    if probe.get("sv3d_present") is not True or probe.get("proj_present") is not True:
        raise PhotorealProjectionAuthorityError("ambiguous projection source lacks Spherical V2 sv3d/proj authority")
    if probe.get("prhd_present") is not True:
        raise PhotorealProjectionAuthorityError("ambiguous projection source lacks Spherical V2 projection header authority")
    if probe.get("prhd_version") != 0 or probe.get("prhd_flags") != 0:
        raise PhotorealProjectionAuthorityError(
            "ambiguous projection source uses unsupported Spherical V2 projection header semantics"
        )

    projection_type = str(probe.get("projection_type") or "").strip()
    if projection_type not in V2_PROJECTION_TYPES:
        raise PhotorealProjectionAuthorityError(
            f"ambiguous projection source has unsupported or non-unique Spherical V2 projection type: {projection_type or 'unknown'}"
        )
    if probe.get("projection_data_version") != 0 or probe.get("projection_data_flags") != 0:
        raise PhotorealProjectionAuthorityError(
            "ambiguous projection source uses unsupported Spherical V2 projection-data semantics"
        )

    if projection_type == "equi":
        if probe.get("equirectangular_bounds_valid") is not True:
            raise PhotorealProjectionAuthorityError(
                "ambiguous projection source has invalid Spherical V2 equirectangular bounds"
            )
    elif projection_type == "cbmp":
        if probe.get("cubemap_layout_known") is not True:
            raise PhotorealProjectionAuthorityError(
                "ambiguous projection source uses unsupported Spherical V2 cubemap layout"
            )
    else:
        if probe.get("mesh_projection_crc32_matches") is not True:
            raise PhotorealProjectionAuthorityError(
                "ambiguous projection source has invalid Spherical V2 mesh projection CRC"
            )
        if probe.get("mesh_projection_encoding_supported") is not True:
            raise PhotorealProjectionAuthorityError(
                "ambiguous projection source uses unsupported Spherical V2 mesh encoding"
            )
        _positive_int(probe.get("mesh_projection_payload_bytes"), label="Spherical V2 mesh payload size")
    return dict(probe)


def _resolve_stereo_layout(planned_layout: Any, probe: Mapping[str, Any]) -> str:
    layout = _text(planned_layout, label="dataset stereo layout", maximum=128)
    observed_layout: str | None = None
    if probe.get("st3d_present") is True:
        if probe.get("st3d_version") != 0 or probe.get("st3d_flags") != 0:
            raise PhotorealProjectionAuthorityError(
                "ambiguous projection source uses unsupported Spherical V2 stereo box semantics"
            )
        observed_mode = str(probe.get("stereo_mode") or "").strip()
        observed_layout = V2_STEREO_TO_LAYOUT.get(observed_mode)
        if observed_layout is None:
            raise PhotorealProjectionAuthorityError(
                f"ambiguous projection source uses unsupported Spherical V2 stereo mode: {observed_mode or 'unknown'}"
            )
    if layout in KNOWN_STEREO_LAYOUTS:
        if observed_layout is not None and observed_layout != layout:
            raise PhotorealProjectionAuthorityError(
                "dataset stereo layout conflicts with authoritative Spherical V2 st3d metadata"
            )
        return layout
    if observed_layout is None:
        raise PhotorealProjectionAuthorityError(
            "ambiguous projection source has no authoritative Spherical V2 st3d stereo layout"
        )
    return observed_layout


def resolve_v2_projection_ambiguity(plan: Mapping[str, Any], receipt: Mapping[str, Any]) -> tuple[dict[str, Any], int]:
    version = plan.get("version")
    if plan.get("format") != PLAN_FORMAT or isinstance(version, bool) or version != PLAN_VERSION:
        raise PhotorealProjectionAuthorityError("photoreal dataset plan format/version mismatch")
    performer_id = _text(plan.get("performer_id"), label="dataset performer id", maximum=256)
    if performer_id != _text(receipt.get("performer_id"), label="receipt performer id", maximum=256):
        raise PhotorealProjectionAuthorityError("dataset plan/source receipt performer mismatch")
    if plan.get("teacher_training_authorized") is not False:
        raise PhotorealProjectionAuthorityError("projection authority requires a pre-training dataset plan")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealProjectionAuthorityError("photoreal dataset plan authority boundary is invalid")
    if plan.get("production_activation") is not False:
        raise PhotorealProjectionAuthorityError("photoreal dataset plan crossed production authority")

    receipt_sources = _receipt_sources(receipt)
    result = copy.deepcopy(dict(plan))
    seen: set[str] = set()
    resolved_count = 0
    for split in ("train", "evaluation"):
        values = result.get(split)
        if not isinstance(values, list) or not values:
            raise PhotorealProjectionAuthorityError(f"photoreal dataset plan has no {split} sources")
        for raw in values:
            if not isinstance(raw, dict):
                raise PhotorealProjectionAuthorityError("photoreal dataset plan source is invalid")
            source_key = _text(raw.get("source_id"), label="dataset source key")
            if source_key in seen:
                raise PhotorealProjectionAuthorityError("photoreal dataset plan repeats a source key")
            seen.add(source_key)
            verified = receipt_sources.get(source_key)
            if verified is None:
                raise PhotorealProjectionAuthorityError("dataset plan/source receipt source universe mismatch")
            kind = _text(raw.get("kind"), label="dataset source kind", maximum=16)
            if kind != verified["kind"]:
                raise PhotorealProjectionAuthorityError("dataset plan/source receipt source kind mismatch")
            if kind != "video" or raw.get("projection") != AMBIGUOUS_PROJECTION:
                continue
            probe = _probe_v2_projection(verified["resolved_path"])
            raw["projection"] = str(probe["projection_type"])
            raw["stereo_layout"] = _resolve_stereo_layout(raw.get("stereo_layout"), probe)
            resolved_count += 1
    if seen != set(receipt_sources):
        raise PhotorealProjectionAuthorityError("dataset plan/source receipt source universe mismatch")
    return result, resolved_count
