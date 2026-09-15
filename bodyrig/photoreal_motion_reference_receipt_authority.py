from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping

from .photoreal_animated_review_plan import MOTION_REVIEW_DIMENSIONS
from .photoreal_motion_reference_materialization_authority import (
    ANCHOR_FIELDS,
    FRAME_FIELDS,
    WINDOW_FIELDS,
    PhotorealMotionReferenceAuthorityError,
    validate_motion_materialization_receipt,
)
from .photoreal_motion_reference_materializer import ADAPTER, SAMPLE_FPS


class PhotorealMotionReferenceReceiptAuthorityError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealMotionReferenceReceiptAuthorityError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealMotionReferenceReceiptAuthorityError(f"{label} is invalid")
    return clean


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealMotionReferenceReceiptAuthorityError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealMotionReferenceReceiptAuthorityError(f"{label} is invalid")
    return clean


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealMotionReferenceReceiptAuthorityError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise PhotorealMotionReferenceReceiptAuthorityError(f"{label} is invalid")
    return round(result, 6)


def _window_id(*, source_key: str, eye: str, start: float, end: float) -> str:
    payload = {
        "source_key": source_key,
        "eye": eye,
        "window_start_seconds": start,
        "window_end_seconds": end,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _observation_id(*, source_key: str, frame_sha256: str, timestamp_seconds: float, eye: str) -> str:
    payload = {
        "source_key": source_key,
        "frame_sha256": frame_sha256,
        "timestamp_seconds": timestamp_seconds,
        "eye": eye,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _relative_path(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealMotionReferenceReceiptAuthorityError(f"{label} escapes review root")
    return clean


def validate_motion_materialization_receipt_strict(value: Mapping[str, Any]) -> dict[str, Any]:
    try:
        receipt = validate_motion_materialization_receipt(value)
    except PhotorealMotionReferenceAuthorityError as exc:
        raise PhotorealMotionReferenceReceiptAuthorityError(str(exc)) from exc

    if receipt.get("adapter") != ADAPTER:
        raise PhotorealMotionReferenceReceiptAuthorityError("motion materialization receipt adapter mismatch")
    _sha(receipt.get("revision"), label="motion materializer revision")
    _text(receipt.get("performer_id"), label="performer id", maximum=256)
    _text(receipt.get("selected_epoch_id"), label="selected epoch id", maximum=256)
    if receipt.get("decode_semantics") != "opencv-bgr-array-v1":
        raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt decode semantics mismatch")
    if receipt.get("frame_hash_semantics") != "sha256(shape-ascii-newline+contiguous-bgr-bytes)":
        raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt frame hash semantics mismatch")

    source_count = receipt.get("source_count")
    window_count = receipt.get("window_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count < 1:
        raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt source_count is invalid")
    if isinstance(window_count, bool) or not isinstance(window_count, int) or window_count < 1:
        raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window_count is invalid")

    windows = receipt.get("materialized_windows")
    if not isinstance(windows, list) or len(windows) != window_count:
        raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window_count does not match windows")

    seen_windows: set[str] = set()
    source_keys: set[str] = set()
    all_dimensions: set[str] = set()
    seen_png_paths: set[str] = set()
    normalized_windows: list[dict[str, Any]] = []

    for raw in windows:
        if not isinstance(raw, Mapping) or set(raw) != WINDOW_FIELDS:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window fields must match v1 exactly")
        source_key = _text(raw.get("source_key"), label="motion receipt source key")
        eye = raw.get("eye")
        if eye not in {"mono", "left", "right"}:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window eye is invalid")
        start = _finite(raw.get("window_start_seconds"), label="motion receipt window start")
        end = _finite(raw.get("window_end_seconds"), label="motion receipt window end")
        if end <= start:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window is empty")
        if raw.get("sample_fps") != SAMPLE_FPS:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window sample FPS mismatch")
        window_id = _sha(raw.get("window_id"), label="motion receipt window id")
        if window_id != _window_id(source_key=source_key, eye=str(eye), start=start, end=end):
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window id does not match provenance")
        if window_id in seen_windows:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt repeats window id")
        seen_windows.add(window_id)
        source_keys.add(source_key)

        dimensions = raw.get("dimensions")
        if not isinstance(dimensions, list) or not dimensions:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window dimensions are invalid")
        if any(not isinstance(item, str) or item not in MOTION_REVIEW_DIMENSIONS for item in dimensions):
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt contains unknown review dimension")
        if dimensions != sorted(set(dimensions)):
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window dimensions are not canonical")
        window_dimensions = set(dimensions)
        all_dimensions.update(window_dimensions)
        if raw.get("source_hash_verified") is not True or raw.get("all_anchor_hashes_verified") is not True:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window lacks source/anchor verification")

        anchors = raw.get("anchors")
        if not isinstance(anchors, list) or not anchors:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window contains no anchors")
        seen_anchors: set[str] = set()
        anchor_dimensions: set[str] = set()
        normalized_anchors: list[dict[str, Any]] = []
        for anchor in anchors:
            if not isinstance(anchor, Mapping) or set(anchor) != ANCHOR_FIELDS:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt anchor fields must match v1 exactly")
            timestamp = _finite(anchor.get("timestamp_seconds"), label="motion receipt anchor timestamp")
            if not start <= timestamp <= end:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt anchor timestamp lies outside window")
            expected_sha = _sha(anchor.get("expected_frame_sha256"), label="motion receipt expected anchor SHA-256")
            observed_sha = _sha(anchor.get("observed_frame_sha256"), label="motion receipt observed anchor SHA-256")
            if observed_sha != expected_sha or anchor.get("frame_hash_verified") is not True:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt anchor frame was not exactly verified")
            observation_id = _sha(anchor.get("observation_id"), label="motion receipt observation id")
            expected_observation_id = _observation_id(
                source_key=source_key,
                frame_sha256=expected_sha,
                timestamp_seconds=timestamp,
                eye=str(eye),
            )
            if observation_id != expected_observation_id:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt observation id does not match provenance")
            if observation_id in seen_anchors:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt repeats anchor observation")
            seen_anchors.add(observation_id)
            anchor_dims = anchor.get("dimensions")
            if not isinstance(anchor_dims, list) or not anchor_dims:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt anchor dimensions are invalid")
            if any(not isinstance(item, str) or item not in window_dimensions for item in anchor_dims):
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt anchor dimension is outside window authority")
            if anchor_dims != sorted(set(anchor_dims)):
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt anchor dimensions are not canonical")
            anchor_dimensions.update(anchor_dims)
            normalized_anchors.append(dict(anchor))
        if anchor_dimensions != window_dimensions:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt anchors do not cover window dimensions exactly")

        frames = raw.get("frames")
        frame_count = raw.get("frame_count")
        if not isinstance(frames, list) or not frames:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt window contains no frames")
        if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count != len(frames):
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt frame_count does not match frames")
        expected_count = int(math.floor((end - start) * SAMPLE_FPS)) + 1
        if frame_count != expected_count:
            raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt frame_count violates deterministic cadence")
        normalized_frames: list[dict[str, Any]] = []
        for index, frame in enumerate(frames):
            if not isinstance(frame, Mapping) or set(frame) != FRAME_FIELDS:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt frame fields must match v1 exactly")
            if frame.get("index") != index:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt frame indexes are not contiguous")
            requested = _finite(frame.get("requested_timestamp_seconds"), label="motion receipt frame timestamp")
            expected_timestamp = round(min(end, start + index / SAMPLE_FPS), 6)
            if requested != expected_timestamp:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt frame timestamp violates deterministic cadence")
            _sha(frame.get("decoded_frame_sha256"), label="motion receipt decoded frame SHA-256")
            relative = _relative_path(frame.get("png_relative_path"), label="motion receipt PNG path")
            expected_relative = f"motion/{window_id}/{index:04d}.png"
            if relative != expected_relative:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt PNG path is not canonical")
            if relative in seen_png_paths:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt repeats PNG path")
            seen_png_paths.add(relative)
            size = frame.get("png_size_bytes")
            if isinstance(size, bool) or not isinstance(size, int) or size < 1:
                raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt PNG size is invalid")
            _sha(frame.get("png_sha256"), label="motion receipt PNG SHA-256")
            normalized_frames.append(dict(frame))

        normalized_window = dict(raw)
        normalized_window["anchors"] = sorted(normalized_anchors, key=lambda item: item["observation_id"])
        normalized_window["frames"] = normalized_frames
        normalized_windows.append(normalized_window)

    if len(source_keys) != source_count:
        raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt source_count does not match unique source universe")
    if all_dimensions != set(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealMotionReferenceReceiptAuthorityError("motion receipt does not cover canonical motion-review universe")

    result = dict(receipt)
    result["materialized_windows"] = sorted(normalized_windows, key=lambda item: item["window_id"])
    return result
