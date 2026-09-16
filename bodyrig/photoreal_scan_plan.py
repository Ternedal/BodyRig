from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Mapping

PLAN_FORMAT = "bodyrig-photoreal-dataset-plan"
PLAN_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-source-receipt"
RECEIPT_VERSION = 1
FORMAT = "bodyrig-photoreal-scan-plan"
VERSION = 1

TARGET_VIDEO_INTERVAL_SECONDS = 10.0
MIN_VIDEO_SCOUT_SAMPLES = 12
MAX_VIDEO_SCOUT_SAMPLES = 120
MAX_TOTAL_PLANNED_OBSERVATIONS = 120_000
KNOWN_STEREO_LAYOUTS = {"mono", "side-by-side", "over-under", "mesh-custom"}
KNOWN_PROJECTIONS = {"flat", "vr180", "vr360", "equirectangular", "equi", "mshp", "cbmp"}
IDENTITY_BOOTSTRAP_DECODE_MODES = {"image-direct", "rectilinear-mono", "rectilinear-stereo-split"}


class PhotorealScanPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealScanPlanError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealScanPlanError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealScanPlanError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealScanPlanError(f"{label} is invalid")
    return result


def _positive_number(value: Any, *, label: str) -> float:
    if isinstance(value, bool):
        raise PhotorealScanPlanError(f"{label} is invalid")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealScanPlanError(f"{label} is invalid") from exc
    if not math.isfinite(result) or result <= 0:
        raise PhotorealScanPlanError(f"{label} must be finite and positive")
    return result


def _nonnegative_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool):
        raise PhotorealScanPlanError(f"{label} is invalid")
    try:
        result = int(value)
    except (TypeError, ValueError) as exc:
        raise PhotorealScanPlanError(f"{label} is invalid") from exc
    if result < 0:
        raise PhotorealScanPlanError(f"{label} cannot be negative")
    return result


def _plan_sources(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise PhotorealScanPlanError("photoreal dataset plan format/version mismatch")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealScanPlanError("photoreal dataset plan authority boundary is invalid")
    if plan.get("production_activation") is not False:
        raise PhotorealScanPlanError("photoreal dataset plan crossed production authority")
    if plan.get("teacher_training_authorized") is not False:
        raise PhotorealScanPlanError("scout scan requires a pre-training dataset plan")
    if plan.get("identity_bootstrap_policy") != "train-only-single-performer-direct-binding-v1":
        raise PhotorealScanPlanError("photoreal dataset plan identity bootstrap policy mismatch")

    sources: dict[str, dict[str, Any]] = {}
    for split in ("train", "evaluation"):
        values = plan.get(split)
        if not isinstance(values, list) or not values:
            raise PhotorealScanPlanError(f"photoreal dataset plan has no {split} sources")
        for raw in values:
            if not isinstance(raw, Mapping):
                raise PhotorealScanPlanError(f"photoreal dataset plan {split} source is invalid")
            source_key = _text(raw.get("source_id"), label="dataset source key")
            if source_key in sources:
                raise PhotorealScanPlanError(f"dataset plan repeats source key: {source_key}")
            kind = _text(raw.get("kind"), label="dataset source kind")
            if kind not in {"video", "image"}:
                raise PhotorealScanPlanError(f"unsupported dataset source kind: {kind}")
            source_binding = _text(raw.get("source_binding"), label="dataset source binding", maximum=128)
            performer_count = _nonnegative_int(raw.get("performer_count"), label="dataset performer_count")
            sources[source_key] = {
                **dict(raw),
                "source_key": source_key,
                "split": split,
                "group_id": _text(raw.get("group_id"), label="dataset source group"),
                "kind": kind,
                "source_binding": source_binding,
                "performer_count": performer_count,
            }
    return sources


def _receipt_sources(receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if receipt.get("format") != RECEIPT_FORMAT or receipt.get("version") != RECEIPT_VERSION:
        raise PhotorealScanPlanError("photoreal source receipt format/version mismatch")
    if receipt.get("all_sources_readable") is not True or receipt.get("all_sources_sha256_bound") is not True:
        raise PhotorealScanPlanError("photoreal source receipt is incomplete")
    if receipt.get("source_keys_path_specific") is not True:
        raise PhotorealScanPlanError("photoreal source receipt lacks path-specific keys")
    if receipt.get("build_only") is not True or receipt.get("runtime_dependency") is not False:
        raise PhotorealScanPlanError("photoreal source receipt authority boundary is invalid")
    if receipt.get("production_activation") is not False:
        raise PhotorealScanPlanError("photoreal source receipt crossed production authority")

    values = receipt.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealScanPlanError("photoreal source receipt contains no sources")
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealScanPlanError("photoreal source receipt source is invalid")
        source_key = _text(raw.get("source_key"), label="receipt source key")
        if source_key in result:
            raise PhotorealScanPlanError(f"photoreal source receipt repeats source key: {source_key}")
        result[source_key] = {
            "kind": _text(raw.get("kind"), label="receipt source kind"),
            "sha256": _sha(raw.get("sha256"), label="receipt source SHA-256"),
            "resolved_path": _text(raw.get("resolved_path"), label="receipt resolved path"),
        }
    return result


def _video_sample_count(duration_seconds: float) -> int:
    requested = int(math.ceil(duration_seconds / TARGET_VIDEO_INTERVAL_SECONDS))
    return max(MIN_VIDEO_SCOUT_SAMPLES, min(MAX_VIDEO_SCOUT_SAMPLES, requested))


def _video_timestamps(duration_seconds: float, sample_count: int) -> list[float]:
    return [round(duration_seconds * (index + 0.5) / sample_count, 6) for index in range(sample_count)]


def _eyes_for_layout(stereo_layout: str) -> list[str]:
    if stereo_layout == "mono":
        return ["mono"]
    if stereo_layout in {"side-by-side", "over-under", "mesh-custom"}:
        return ["left", "right"]
    raise PhotorealScanPlanError(
        f"stereo layout '{stereo_layout}' is not decode-authoritative; classify it before frame analysis"
    )


def _decode_mode(projection: str, stereo_layout: str) -> str:
    if projection == "projection-ambiguous-2to1":
        raise PhotorealScanPlanError(
            "projection-ambiguous-2to1 source cannot enter frame analysis until projection is resolved"
        )
    if projection not in KNOWN_PROJECTIONS:
        raise PhotorealScanPlanError(f"unsupported projection for scout analysis: {projection}")
    if stereo_layout not in KNOWN_STEREO_LAYOUTS:
        raise PhotorealScanPlanError(
            f"stereo layout '{stereo_layout}' cannot enter frame analysis until it is resolved"
        )
    if stereo_layout == "mesh-custom" and projection != "mshp":
        raise PhotorealScanPlanError("mesh-custom stereo layout requires exact mshp projection authority")
    if projection == "flat" and stereo_layout == "mono":
        return "rectilinear-mono"
    if projection == "flat":
        return "rectilinear-stereo-split"
    return "spatial-deprojection-required"


def _identity_bootstrap_eligible(source: Mapping[str, Any]) -> bool:
    if source["split"] != "train" or int(source["performer_count"]) != 1:
        return False
    if source.get("decode_mode") not in IDENTITY_BOOTSTRAP_DECODE_MODES:
        return False
    if source["kind"] == "video":
        return source["source_binding"] == "scene-performer"
    return source["source_binding"] == "direct-performer"


def build_scan_plan(plan: Mapping[str, Any], receipt: Mapping[str, Any]) -> dict[str, Any]:
    performer_id = _text(plan.get("performer_id"), label="dataset performer id", maximum=256)
    if performer_id != _text(receipt.get("performer_id"), label="receipt performer id", maximum=256):
        raise PhotorealScanPlanError("dataset plan/source receipt performer mismatch")

    plan_sources = _plan_sources(plan)
    receipt_sources = _receipt_sources(receipt)
    if set(plan_sources) != set(receipt_sources):
        raise PhotorealScanPlanError("dataset plan/source receipt source universe mismatch")

    sources: list[dict[str, Any]] = []
    total_observations = 0
    for source_key in sorted(plan_sources):
        planned = plan_sources[source_key]
        verified = receipt_sources[source_key]
        if verified["kind"] != planned["kind"]:
            raise PhotorealScanPlanError(f"source kind mismatch for {source_key}")

        projection_authority: dict[str, Any] | None = None
        if planned["kind"] == "image":
            samples = [{"timestamp_seconds": None, "eye": "mono"}]
            decode_mode = "image-direct"
            projection = "flat"
            stereo_layout = "mono"
        else:
            duration = _positive_number(planned.get("duration_seconds"), label=f"video duration for {source_key}")
            projection = _text(planned.get("projection"), label=f"projection for {source_key}", maximum=128)
            stereo_layout = _text(planned.get("stereo_layout"), label=f"stereo layout for {source_key}", maximum=128)
            decode_mode = _decode_mode(projection, stereo_layout)
            if projection in {"equi", "mshp", "cbmp"}:
                raw_authority = planned.get("projection_authority")
                if not isinstance(raw_authority, Mapping):
                    raise PhotorealScanPlanError(
                        f"exact Spherical V2 projection lacks projection authority: {source_key}"
                    )
                projection_authority = copy.deepcopy(dict(raw_authority))
                if projection_authority.get("projection_type") != projection:
                    raise PhotorealScanPlanError(
                        f"Spherical V2 projection authority type mismatch: {source_key}"
                    )
                if projection_authority.get("deprojection_authority") is not False:
                    raise PhotorealScanPlanError(
                        f"scan plan cannot inherit deprojection authority: {source_key}"
                    )
            if stereo_layout == "mesh-custom":
                if (
                    projection != "mshp"
                    or projection_authority is None
                    or projection_authority.get("mesh_projection_mesh_count") != 2
                ):
                    raise PhotorealScanPlanError(
                        f"mesh-custom stereo requires authoritative two-mesh projection geometry: {source_key}"
                    )
            eyes = _eyes_for_layout(stereo_layout)
            timestamps = _video_timestamps(duration, _video_sample_count(duration))
            samples = [
                {"timestamp_seconds": timestamp, "eye": eye}
                for timestamp in timestamps
                for eye in eyes
            ]

        total_observations += len(samples)
        if total_observations > MAX_TOTAL_PLANNED_OBSERVATIONS:
            raise PhotorealScanPlanError(
                f"scout plan exceeds explicit observation safety bound {MAX_TOTAL_PLANNED_OBSERVATIONS}"
            )

        source = {
            "source_key": source_key,
            "source_sha256": verified["sha256"],
            "resolved_path": verified["resolved_path"],
            "kind": planned["kind"],
            "split": planned["split"],
            "group_id": planned["group_id"],
            "source_binding": planned["source_binding"],
            "performer_count": planned["performer_count"],
            "projection": projection,
            "projection_authority": projection_authority,
            "stereo_layout": stereo_layout,
            "decode_mode": decode_mode,
            "sample_count": len(samples),
            "samples": samples,
        }
        source["identity_bootstrap_eligible"] = _identity_bootstrap_eligible(source)
        sources.append(source)

    bootstrap_sources = [item for item in sources if item["identity_bootstrap_eligible"]]
    return {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "performer_name": str(plan.get("performer_name") or ""),
        "strategy": "uniform-midpoint-scout-v1",
        "target_video_interval_seconds": TARGET_VIDEO_INTERVAL_SECONDS,
        "minimum_video_scout_samples": MIN_VIDEO_SCOUT_SAMPLES,
        "maximum_video_scout_samples": MAX_VIDEO_SCOUT_SAMPLES,
        "source_count": len(sources),
        "planned_observation_count": total_observations,
        "identity_bootstrap_policy": "train-only-single-performer-direct-binding-v1",
        "identity_bootstrap_source_count": len(bootstrap_sources),
        "identity_bootstrap_group_count": len({item["group_id"] for item in bootstrap_sources}),
        "sources": sources,
        "all_sources_sha256_bound": True,
        "train_evaluation_assignment_inherited": True,
        "frame_analyzer_required": True,
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def build_scan_plan_files(
    plan_path: str | Path,
    receipt_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="photoreal dataset plan")
    receipt = _read_json(receipt_path, label="photoreal source receipt")
    result = build_scan_plan(plan, receipt)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealScanPlanError(f"photoreal scan plan already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
