from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_motion_reference_materializer import (
    RESULT_FORMAT,
    SAMPLE_FPS,
    VERSION,
    PhotorealMotionReferenceMaterializerError,
    validate_motion_materialization_result,
)

RECEIPT_FORMAT = "bodyrig-photoreal-motion-reference-materialization-receipt"
WINDOW_FIELDS = {
    "window_id", "source_key", "eye", "dimensions", "window_start_seconds",
    "window_end_seconds", "sample_fps", "anchors", "source_hash_verified",
    "all_anchor_hashes_verified", "frame_count", "frames",
}
ANCHOR_FIELDS = {
    "observation_id", "timestamp_seconds", "expected_frame_sha256", "observed_frame_sha256",
    "dimensions", "frame_hash_verified",
}
FRAME_FIELDS = {
    "index", "requested_timestamp_seconds", "decoded_frame_sha256",
    "png_relative_path", "png_size_bytes", "png_sha256",
}


class PhotorealMotionReferenceAuthorityError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealMotionReferenceAuthorityError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealMotionReferenceAuthorityError(f"{label} is invalid")
    return clean


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealMotionReferenceAuthorityError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise PhotorealMotionReferenceAuthorityError(f"{label} is invalid")
    return round(result, 6)


def _digest_without(value: Mapping[str, Any], key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _expected_window_map(request: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for source in request["sources"]:
        source_key = str(source["source_key"])
        for window in source["windows"]:
            window_id = _sha(window.get("window_id"), label="planned motion window id")
            if window_id in result:
                raise PhotorealMotionReferenceAuthorityError("motion request repeats window id")
            result[window_id] = {
                "source_key": source_key,
                "eye": window["eye"],
                "dimensions": sorted(window["dimensions"]),
                "window_start_seconds": _finite(window["window_start_seconds"], label="planned window start"),
                "window_end_seconds": _finite(window["window_end_seconds"], label="planned window end"),
                "anchors": {
                    _sha(anchor["observation_id"], label="planned anchor observation id"): {
                        "timestamp_seconds": _finite(anchor["timestamp_seconds"], label="planned anchor timestamp"),
                        "expected_frame_sha256": _sha(anchor["expected_frame_sha256"], label="planned anchor frame SHA-256"),
                        "dimensions": sorted(anchor["dimensions"]),
                    }
                    for anchor in window["anchors"]
                },
            }
    return result


def validate_motion_materialization_authority(
    value: Mapping[str, Any],
    *,
    request: Mapping[str, Any],
    output_dir: Path,
) -> dict[str, Any]:
    try:
        normalized = validate_motion_materialization_result(value, request=request, output_dir=output_dir)
    except PhotorealMotionReferenceMaterializerError as exc:
        raise PhotorealMotionReferenceAuthorityError(str(exc)) from exc
    if normalized.get("format") != RESULT_FORMAT or normalized.get("version") != VERSION:
        raise PhotorealMotionReferenceAuthorityError("motion materialization result format/version mismatch")
    expected = _expected_window_map(request)
    windows = normalized.get("materialized_windows")
    if not isinstance(windows, list) or len(windows) != len(expected):
        raise PhotorealMotionReferenceAuthorityError("motion materialization window universe mismatch")
    strict_windows: list[dict[str, Any]] = []
    for raw in windows:
        if not isinstance(raw, Mapping) or set(raw) != WINDOW_FIELDS:
            raise PhotorealMotionReferenceAuthorityError("motion materialization window fields must match v1 exactly")
        window_id = _sha(raw.get("window_id"), label="motion window id")
        planned = expected.get(window_id)
        if planned is None:
            raise PhotorealMotionReferenceAuthorityError("motion materialization contains unplanned window")
        for key in ("source_key", "eye"):
            if raw.get(key) != planned[key]:
                raise PhotorealMotionReferenceAuthorityError(f"motion materialization window provenance mismatch: {key}")
        if sorted(raw.get("dimensions") or []) != planned["dimensions"]:
            raise PhotorealMotionReferenceAuthorityError("motion materialization dimension binding mismatch")
        start = _finite(raw.get("window_start_seconds"), label="motion window start")
        end = _finite(raw.get("window_end_seconds"), label="motion window end")
        if (start, end) != (planned["window_start_seconds"], planned["window_end_seconds"]):
            raise PhotorealMotionReferenceAuthorityError("motion materialization window timing mismatch")
        if raw.get("sample_fps") != SAMPLE_FPS:
            raise PhotorealMotionReferenceAuthorityError("motion materialization sample FPS mismatch")
        if raw.get("source_hash_verified") is not True or raw.get("all_anchor_hashes_verified") is not True:
            raise PhotorealMotionReferenceAuthorityError("motion materialization source/anchor verification is incomplete")

        anchors = raw.get("anchors")
        if not isinstance(anchors, list) or len(anchors) != len(planned["anchors"]):
            raise PhotorealMotionReferenceAuthorityError("motion materialization anchor universe mismatch")
        seen_anchors: set[str] = set()
        strict_anchors: list[dict[str, Any]] = []
        for anchor in anchors:
            if not isinstance(anchor, Mapping) or set(anchor) != ANCHOR_FIELDS:
                raise PhotorealMotionReferenceAuthorityError("motion anchor fields must match v1 exactly")
            observation_id = _sha(anchor.get("observation_id"), label="motion anchor observation id")
            authority = planned["anchors"].get(observation_id)
            if authority is None or observation_id in seen_anchors:
                raise PhotorealMotionReferenceAuthorityError("motion materialization contains unknown/duplicate anchor")
            seen_anchors.add(observation_id)
            timestamp = _finite(anchor.get("timestamp_seconds"), label="motion anchor timestamp")
            expected_sha = _sha(anchor.get("expected_frame_sha256"), label="expected motion anchor frame SHA-256")
            observed_sha = _sha(anchor.get("observed_frame_sha256"), label="observed motion anchor frame SHA-256")
            if timestamp != authority["timestamp_seconds"] or expected_sha != authority["expected_frame_sha256"]:
                raise PhotorealMotionReferenceAuthorityError("motion anchor provenance differs from plan")
            if observed_sha != expected_sha or anchor.get("frame_hash_verified") is not True:
                raise PhotorealMotionReferenceAuthorityError("motion anchor frame hash was not exactly verified")
            if sorted(anchor.get("dimensions") or []) != authority["dimensions"]:
                raise PhotorealMotionReferenceAuthorityError("motion anchor dimension binding mismatch")
            strict_anchors.append(dict(anchor))
        if seen_anchors != set(planned["anchors"]):
            raise PhotorealMotionReferenceAuthorityError("motion materialization omitted planned anchor")

        frames = raw.get("frames")
        frame_count = raw.get("frame_count")
        if not isinstance(frames, list) or not frames or isinstance(frame_count, bool) or frame_count != len(frames):
            raise PhotorealMotionReferenceAuthorityError("motion materialization frame sequence is invalid")
        expected_count = int(math.floor((end - start) * SAMPLE_FPS)) + 1
        if frame_count != expected_count:
            raise PhotorealMotionReferenceAuthorityError("motion materialization frame count does not match deterministic cadence")
        for index, frame in enumerate(frames):
            if not isinstance(frame, Mapping) or set(frame) != FRAME_FIELDS:
                raise PhotorealMotionReferenceAuthorityError("motion materialization frame fields must match v1 exactly")
            if frame.get("index") != index:
                raise PhotorealMotionReferenceAuthorityError("motion materialization frame indexes are not contiguous")
            requested = _finite(frame.get("requested_timestamp_seconds"), label="motion frame requested timestamp")
            expected_timestamp = round(min(end, start + index / SAMPLE_FPS), 6)
            if requested != expected_timestamp:
                raise PhotorealMotionReferenceAuthorityError("motion frame timestamp does not match deterministic cadence")
            _sha(frame.get("decoded_frame_sha256"), label="decoded motion frame SHA-256")
            _sha(frame.get("png_sha256"), label="motion PNG SHA-256")
        strict_window = dict(raw)
        strict_window["anchors"] = sorted(strict_anchors, key=lambda item: item["observation_id"])
        strict_windows.append(strict_window)
    normalized["materialized_windows"] = sorted(strict_windows, key=lambda item: item["window_id"])
    return normalized


def build_motion_materialization_receipt(validated: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        "format": "bodyrig-photoreal-motion-reference-materialization-receipt",
        "version": VERSION,
        "performer_id": validated["performer_id"],
        "selected_epoch_id": validated["selected_epoch_id"],
        "teacher_input_sha256": validated["teacher_input_sha256"],
        "animation_execution_receipt_sha256": validated["animation_execution_receipt_sha256"],
        "held_out_reference_catalog_sha256": validated["held_out_reference_catalog_sha256"],
        "animated_review_plan_sha256": validated["animated_review_plan_sha256"],
        "adapter": validated["adapter"],
        "revision": validated["revision"],
        "sample_fps": validated["sample_fps"],
        "source_count": validated["source_count"],
        "window_count": validated["window_count"],
        "materialized_windows": validated["materialized_windows"],
        "all_source_hashes_verified": True,
        "all_anchor_hashes_verified": True,
        "artifact_bytes_verified_by_core": True,
        "decode_semantics": validated["decode_semantics"],
        "frame_hash_semantics": validated["frame_hash_semantics"],
        "teacher_process_disclosure": False,
        "reference_motion_bytes_materialized": True,
        "human_animated_visual_acceptance_required": True,
        "animated_teacher_acceptance_authority": False,
        "p3_device_distillation_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["motion_materialization_receipt_sha256"] = _digest_without(result, "motion_materialization_receipt_sha256")
    return result


def validate_motion_materialization_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "format", "version", "performer_id", "selected_epoch_id", "teacher_input_sha256",
        "animation_execution_receipt_sha256", "held_out_reference_catalog_sha256",
        "animated_review_plan_sha256", "adapter", "revision", "sample_fps", "source_count",
        "window_count", "materialized_windows", "all_source_hashes_verified", "all_anchor_hashes_verified",
        "artifact_bytes_verified_by_core", "decode_semantics", "frame_hash_semantics",
        "teacher_process_disclosure", "reference_motion_bytes_materialized",
        "human_animated_visual_acceptance_required", "animated_teacher_acceptance_authority",
        "p3_device_distillation_authorized", "build_only", "runtime_dependency", "production_activation",
        "motion_materialization_receipt_sha256",
    }
    if set(value) != required or value.get("format") != RECEIPT_FORMAT:
        raise PhotorealMotionReferenceAuthorityError("motion materialization receipt fields/format mismatch")
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, (int, float)) or version != VERSION:
        raise PhotorealMotionReferenceAuthorityError("motion materialization receipt version mismatch")
    for key in (
        "teacher_input_sha256", "animation_execution_receipt_sha256", "held_out_reference_catalog_sha256",
        "animated_review_plan_sha256", "revision", "motion_materialization_receipt_sha256",
    ):
        _sha(value.get(key), label=key)
    if value.get("sample_fps") != SAMPLE_FPS:
        raise PhotorealMotionReferenceAuthorityError("motion materialization receipt sample FPS mismatch")
    if value.get("all_source_hashes_verified") is not True or value.get("all_anchor_hashes_verified") is not True:
        raise PhotorealMotionReferenceAuthorityError("motion materialization receipt lacks source/anchor verification")
    if value.get("artifact_bytes_verified_by_core") is not True or value.get("reference_motion_bytes_materialized") is not True:
        raise PhotorealMotionReferenceAuthorityError("motion materialization receipt lacks core/materialization authority")
    if value.get("human_animated_visual_acceptance_required") is not True:
        raise PhotorealMotionReferenceAuthorityError("motion materialization receipt removed human review")
    if value.get("animated_teacher_acceptance_authority") is not False or value.get("p3_device_distillation_authorized") is not False:
        raise PhotorealMotionReferenceAuthorityError("motion materialization receipt crossed downstream authority")
    if value.get("teacher_process_disclosure") is not False or value.get("build_only") is not True or value.get("runtime_dependency") is not False or value.get("production_activation") is not False:
        raise PhotorealMotionReferenceAuthorityError("motion materialization receipt boundary is invalid")
    declared = _sha(value.get("motion_materialization_receipt_sha256"), label="motion materialization receipt SHA-256")
    if declared != _digest_without(value, "motion_materialization_receipt_sha256"):
        raise PhotorealMotionReferenceAuthorityError("motion materialization receipt SHA-256 does not match content")
    return dict(value)


def write_motion_materialization_receipt(validated: Mapping[str, Any], path: str | Path) -> dict[str, Any]:
    receipt = build_motion_materialization_receipt(validated)
    output = Path(path).expanduser().resolve()
    if output.exists():
        raise PhotorealMotionReferenceAuthorityError(f"motion materialization receipt already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return receipt
