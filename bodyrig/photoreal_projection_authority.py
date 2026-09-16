from __future__ import annotations

import copy
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_mesh_projection import PhotorealMeshProjectionError, parse_mesh_projection_file
from .photoreal_spatial_metadata_probe import PhotorealSpatialMetadataProbeError, probe_isobmff_file

PLAN_FORMAT = "bodyrig-photoreal-dataset-plan"
PLAN_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-source-receipt"
RECEIPT_VERSION = 1
SPATIAL_HINT_PROJECTIONS = {"projection-ambiguous-2to1", "vr180", "vr360", "equirectangular"}
V2_PROJECTION_TYPES = {"equi", "mshp", "cbmp"}
KNOWN_STEREO_LAYOUTS = {"mono", "side-by-side", "over-under", "mesh-custom"}
V2_STEREO_TO_LAYOUT = {"mono": "mono", "left-right": "side-by-side", "top-bottom": "over-under"}
PROJECTION_AUTHORITY_FORMAT = "bodyrig-spherical-v2-projection-authority"
PROJECTION_AUTHORITY_VERSION = 1


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


def _nonnegative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PhotorealProjectionAuthorityError(f"{label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealProjectionAuthorityError(f"{label} is invalid") from exc
    if result < 0:
        raise PhotorealProjectionAuthorityError(f"{label} cannot be negative")
    return result


def _finite_number(value: Any, *, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool):
        raise PhotorealProjectionAuthorityError(f"{label} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealProjectionAuthorityError(f"{label} is invalid") from exc
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise PhotorealProjectionAuthorityError(f"{label} is outside its valid range")
    return result


def _fraction(value: Any, *, label: str) -> float:
    return _finite_number(value, label=label, minimum=0.0, maximum=1.0)


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
            "spatial source has no readable authoritative Spherical V2 metadata"
        ) from exc
    if probe.get("probe_status") != "parsed-isobmff":
        raise PhotorealProjectionAuthorityError("spatial source is not a parsed ISO BMFF container")
    if probe.get("sv3d_present") is not True or probe.get("proj_present") is not True:
        raise PhotorealProjectionAuthorityError("spatial source lacks Spherical V2 sv3d/proj authority")
    if probe.get("prhd_present") is not True:
        raise PhotorealProjectionAuthorityError("spatial source lacks Spherical V2 projection header authority")
    if probe.get("prhd_version") != 0 or probe.get("prhd_flags") != 0:
        raise PhotorealProjectionAuthorityError(
            "spatial source uses unsupported Spherical V2 projection header semantics"
        )

    projection_type = str(probe.get("projection_type") or "").strip()
    if projection_type not in V2_PROJECTION_TYPES:
        raise PhotorealProjectionAuthorityError(
            f"spatial source has unsupported or non-unique Spherical V2 projection type: {projection_type or 'unknown'}"
        )
    if probe.get("projection_data_version") != 0 or probe.get("projection_data_flags") != 0:
        raise PhotorealProjectionAuthorityError(
            "spatial source uses unsupported Spherical V2 projection-data semantics"
        )

    if projection_type == "equi":
        if probe.get("equirectangular_bounds_valid") is not True:
            raise PhotorealProjectionAuthorityError("spatial source has invalid Spherical V2 equirectangular bounds")
    elif projection_type == "cbmp":
        if probe.get("cubemap_layout_known") is not True:
            raise PhotorealProjectionAuthorityError("spatial source uses unsupported Spherical V2 cubemap layout")
    else:
        if probe.get("mesh_projection_crc32_matches") is not True:
            raise PhotorealProjectionAuthorityError("spatial source has invalid Spherical V2 mesh projection CRC")
        if probe.get("mesh_projection_encoding_supported") is not True:
            raise PhotorealProjectionAuthorityError("spatial source uses unsupported Spherical V2 mesh encoding")
        payload_bytes = _positive_int(
            probe.get("mesh_projection_payload_bytes"),
            label="Spherical V2 mesh payload size",
        )
        try:
            geometry = parse_mesh_projection_file(path, materialize=False)
        except (OSError, PhotorealMeshProjectionError) as exc:
            raise PhotorealProjectionAuthorityError(
                "spatial source mesh projection geometry is not parse-authoritative"
            ) from exc
        if geometry.get("projection_data_version") != 0 or geometry.get("projection_data_flags") != 0:
            raise PhotorealProjectionAuthorityError(
                "spatial source mesh geometry uses unsupported projection-data semantics"
            )
        if geometry.get("mesh_projection_crc32_matches") is not True:
            raise PhotorealProjectionAuthorityError("spatial source mesh geometry CRC is invalid")
        if geometry.get("mesh_projection_crc32") != probe.get("mesh_projection_crc32"):
            raise PhotorealProjectionAuthorityError("spatial source mesh CRC disagrees between metadata probes")
        if geometry.get("encoding") != probe.get("mesh_projection_encoding"):
            raise PhotorealProjectionAuthorityError("spatial source mesh encoding disagrees between metadata probes")
        if int(geometry.get("encoded_payload_bytes") or 0) != payload_bytes:
            raise PhotorealProjectionAuthorityError(
                "spatial source mesh payload size disagrees between metadata probes"
            )
        probe = {
            **dict(probe),
            "mesh_projection_geometry_valid": True,
            "mesh_projection_geometry_sha256": geometry["decompressed_payload_sha256"],
            "mesh_projection_mesh_count": geometry["mesh_count"],
            "mesh_projection_total_vertex_count": geometry["total_vertex_count"],
            "mesh_projection_total_index_count": geometry["total_index_count"],
            "mesh_projection_texture_ids": geometry["texture_ids"],
            "mesh_projection_index_types": geometry["index_types"],
            "mesh_projection_unknown_box_types": geometry["unknown_box_types"],
        }
    return dict(probe)


def _resolve_stereo_layout(planned_layout: Any, probe: Mapping[str, Any]) -> str:
    layout = _text(planned_layout, label="dataset stereo layout", maximum=128)
    observed_layout: str | None = None
    if probe.get("st3d_present") is True:
        if probe.get("st3d_version") != 0 or probe.get("st3d_flags") != 0:
            raise PhotorealProjectionAuthorityError("spatial source uses unsupported Spherical V2 stereo box semantics")
        observed_mode = str(probe.get("stereo_mode") or "").strip()
        observed_layout = V2_STEREO_TO_LAYOUT.get(observed_mode)
        if observed_layout is None and observed_mode == "stereo-custom":
            mesh_count = probe.get("mesh_projection_mesh_count")
            if probe.get("projection_type") == "mshp" and mesh_count == 2:
                observed_layout = "mesh-custom"
        if observed_layout is None:
            raise PhotorealProjectionAuthorityError(
                f"spatial source uses unsupported Spherical V2 stereo mode: {observed_mode or 'unknown'}"
            )
    if layout == "mesh-custom":
        if observed_layout != "mesh-custom":
            raise PhotorealProjectionAuthorityError(
                "dataset mesh-custom layout lacks authoritative two-mesh Spherical V2 stereo-custom metadata"
            )
        return layout
    if layout in KNOWN_STEREO_LAYOUTS:
        if observed_layout is not None and observed_layout != layout:
            raise PhotorealProjectionAuthorityError(
                "dataset stereo layout conflicts with authoritative Spherical V2 st3d metadata"
            )
        return layout
    if observed_layout is None:
        raise PhotorealProjectionAuthorityError("spatial source has no authoritative Spherical V2 st3d stereo layout")
    return observed_layout


def _projection_authority(probe: Mapping[str, Any]) -> dict[str, Any]:
    projection_type = _text(probe.get("projection_type"), label="Spherical V2 projection type", maximum=16)
    yaw = _finite_number(probe.get("projection_pose_yaw_degrees"), label="Spherical V2 projection yaw", minimum=-180.0, maximum=180.0)
    pitch = _finite_number(probe.get("projection_pose_pitch_degrees"), label="Spherical V2 projection pitch", minimum=-90.0, maximum=90.0)
    roll = _finite_number(probe.get("projection_pose_roll_degrees"), label="Spherical V2 projection roll", minimum=-180.0, maximum=180.0)

    equi_bounds: dict[str, float] | None = None
    cubemap_layout: int | None = None
    cubemap_padding: int | None = None
    mesh_crc: str | None = None
    mesh_encoding: str | None = None
    mesh_payload_bytes: int | None = None
    mesh_geometry_sha: str | None = None
    mesh_count: int | None = None
    mesh_vertex_count: int | None = None
    mesh_index_count: int | None = None
    mesh_texture_ids: list[int] | None = None
    mesh_index_types: list[int] | None = None
    mesh_unknown_box_types: list[str] | None = None

    if projection_type == "equi":
        raw_bounds = probe.get("equirectangular_bounds_fraction")
        if not isinstance(raw_bounds, Mapping):
            raise PhotorealProjectionAuthorityError("Spherical V2 equirectangular bounds are missing")
        equi_bounds = {
            name: _fraction(raw_bounds.get(name), label=f"Spherical V2 equirectangular {name} bound")
            for name in ("top", "bottom", "left", "right")
        }
        if equi_bounds["top"] + equi_bounds["bottom"] >= 1.0:
            raise PhotorealProjectionAuthorityError("Spherical V2 vertical equirectangular bounds are empty")
        if equi_bounds["left"] + equi_bounds["right"] >= 1.0:
            raise PhotorealProjectionAuthorityError("Spherical V2 horizontal equirectangular bounds are empty")
    elif projection_type == "cbmp":
        cubemap_layout = _nonnegative_int(probe.get("cubemap_layout"), label="Spherical V2 cubemap layout")
        cubemap_padding = _nonnegative_int(probe.get("cubemap_padding_pixels"), label="Spherical V2 cubemap padding")
    elif projection_type == "mshp":
        mesh_crc = str(probe.get("mesh_projection_crc32") or "").strip().lower()
        if len(mesh_crc) != 8 or any(character not in "0123456789abcdef" for character in mesh_crc):
            raise PhotorealProjectionAuthorityError("Spherical V2 mesh CRC is invalid")
        mesh_encoding = _text(probe.get("mesh_projection_encoding"), label="Spherical V2 mesh encoding", maximum=4)
        if mesh_encoding not in {"raw ", "dfl8"}:
            raise PhotorealProjectionAuthorityError("Spherical V2 mesh encoding is unsupported")
        mesh_payload_bytes = _positive_int(probe.get("mesh_projection_payload_bytes"), label="Spherical V2 mesh payload size")
        if probe.get("mesh_projection_geometry_valid") is not True:
            raise PhotorealProjectionAuthorityError("Spherical V2 mesh geometry lacks parse authority")
        mesh_geometry_sha = _sha(
            probe.get("mesh_projection_geometry_sha256"),
            label="Spherical V2 mesh geometry SHA-256",
        )
        mesh_count = _positive_int(probe.get("mesh_projection_mesh_count"), label="Spherical V2 mesh count")
        if mesh_count > 2:
            raise PhotorealProjectionAuthorityError("Spherical V2 mesh count exceeds v2 maximum")
        mesh_vertex_count = _positive_int(
            probe.get("mesh_projection_total_vertex_count"),
            label="Spherical V2 mesh vertex count",
        )
        mesh_index_count = _positive_int(
            probe.get("mesh_projection_total_index_count"),
            label="Spherical V2 mesh index count",
        )
        raw_texture_ids = probe.get("mesh_projection_texture_ids")
        raw_index_types = probe.get("mesh_projection_index_types")
        raw_unknown = probe.get("mesh_projection_unknown_box_types")
        if not isinstance(raw_texture_ids, list) or any(
            isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 255
            for value in raw_texture_ids
        ):
            raise PhotorealProjectionAuthorityError("Spherical V2 mesh texture IDs are invalid")
        if not isinstance(raw_index_types, list) or any(
            isinstance(value, bool) or not isinstance(value, int) or value not in {0, 1, 2}
            for value in raw_index_types
        ):
            raise PhotorealProjectionAuthorityError("Spherical V2 mesh index types are invalid")
        if not isinstance(raw_unknown, list) or any(
            not isinstance(value, str) or len(value) != 4 for value in raw_unknown
        ):
            raise PhotorealProjectionAuthorityError("Spherical V2 mesh extension box list is invalid")
        mesh_texture_ids = sorted(set(raw_texture_ids))
        mesh_index_types = sorted(set(raw_index_types))
        mesh_unknown_box_types = sorted(set(raw_unknown))
    else:
        raise PhotorealProjectionAuthorityError("unsupported Spherical V2 projection authority type")

    return {
        "format": PROJECTION_AUTHORITY_FORMAT,
        "version": PROJECTION_AUTHORITY_VERSION,
        "projection_type": projection_type,
        "pose_degrees": {"yaw": round(yaw, 6), "pitch": round(pitch, 6), "roll": round(roll, 6)},
        "equirectangular_bounds_fraction": equi_bounds,
        "cubemap_layout": cubemap_layout,
        "cubemap_padding_pixels": cubemap_padding,
        "mesh_projection_crc32": mesh_crc,
        "mesh_projection_encoding": mesh_encoding,
        "mesh_projection_payload_bytes": mesh_payload_bytes,
        "mesh_projection_geometry_sha256": mesh_geometry_sha,
        "mesh_projection_mesh_count": mesh_count,
        "mesh_projection_total_vertex_count": mesh_vertex_count,
        "mesh_projection_total_index_count": mesh_index_count,
        "mesh_projection_texture_ids": mesh_texture_ids,
        "mesh_projection_index_types": mesh_index_types,
        "mesh_projection_unknown_box_types": mesh_unknown_box_types,
        "deprojection_authority": False,
    }


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
            projection_hint = _text(raw.get("projection"), label="dataset source projection", maximum=128)
            if kind != "video" or projection_hint not in SPATIAL_HINT_PROJECTIONS:
                continue
            probe = _probe_v2_projection(verified["resolved_path"])
            raw["projection"] = str(probe["projection_type"])
            raw["stereo_layout"] = _resolve_stereo_layout(raw.get("stereo_layout"), probe)
            raw["projection_authority"] = _projection_authority(probe)
            resolved_count += 1
    if seen != set(receipt_sources):
        raise PhotorealProjectionAuthorityError("dataset plan/source receipt source universe mismatch")
    return result, resolved_count
