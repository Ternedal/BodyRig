from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from .phalp_track_review import _bbox_tlwh

FORMAT = "bodyrig-phalp-attested-track-mask"
VERSION = 1
MAX_REQUESTED_SAMPLES = 12
MAX_MASK_RUNS = 500_000


class PhalpTrackMaskError(ValueError):
    pass


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, (bool, str, bytes)):
        raise PhalpTrackMaskError(f"{label} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise PhalpTrackMaskError(f"{label} must be numeric") from exc
    if not math.isfinite(result):
        raise PhalpTrackMaskError(f"{label} must be finite")
    return result


def _timestamps(value: Sequence[object]) -> list[int]:
    if isinstance(value, (str, bytes, bytearray)):
        raise PhalpTrackMaskError("requested timestamps must be an array")
    rows: list[int] = []
    for raw in value:
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            raise PhalpTrackMaskError("requested timestamp must be a non-negative integer")
        rows.append(raw)
    if not 1 <= len(rows) <= MAX_REQUESTED_SAMPLES:
        raise PhalpTrackMaskError(f"requested timestamps must contain 1..{MAX_REQUESTED_SAMPLES} values")
    if rows != sorted(set(rows)):
        raise PhalpTrackMaskError("requested timestamps must be sorted and unique")
    return rows


def _normalize_mask(value: object, *, expected_height: int, expected_width: int) -> list[list[int]]:
    if isinstance(value, (str, bytes, bytearray)):
        raise PhalpTrackMaskError("decoded PHALP mask must be a 2D array")
    try:
        height = len(value)  # type: ignore[arg-type]
    except TypeError as exc:
        raise PhalpTrackMaskError("decoded PHALP mask must be a 2D array") from exc
    if height != expected_height:
        raise PhalpTrackMaskError("decoded PHALP mask height differs from source frame")
    rows: list[list[int]] = []
    for y in range(height):
        try:
            row_raw = value[y]  # type: ignore[index]
            width = len(row_raw)
        except (TypeError, IndexError) as exc:
            raise PhalpTrackMaskError("decoded PHALP mask row is invalid") from exc
        if width != expected_width:
            raise PhalpTrackMaskError("decoded PHALP mask width differs from source frame")
        row: list[int] = []
        for x in range(width):
            try:
                raw = row_raw[x]
            except (TypeError, IndexError) as exc:
                raise PhalpTrackMaskError("decoded PHALP mask pixel is invalid") from exc
            if isinstance(raw, bool):
                bit = 1 if raw else 0
            else:
                try:
                    numeric = int(raw)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise PhalpTrackMaskError("decoded PHALP mask pixel is non-binary") from exc
                if numeric not in (0, 1):
                    raise PhalpTrackMaskError("decoded PHALP mask pixel is non-binary")
                bit = numeric
            row.append(bit)
        rows.append(row)
    return rows


def _uncompressed_coco_rle(mask: Sequence[Sequence[int]]) -> tuple[list[int], int, tuple[int, int, int, int]]:
    height = len(mask)
    width = len(mask[0]) if height else 0
    if height <= 0 or width <= 0:
        raise PhalpTrackMaskError("decoded PHALP mask is empty")

    counts: list[int] = []
    current = 0
    run = 0
    pixel_count = 0
    min_x, min_y = width, height
    max_x, max_y = -1, -1
    # COCO RLE is column-major (Fortran order), starting with background run.
    for x in range(width):
        for y in range(height):
            bit = int(mask[y][x])
            if bit != current:
                counts.append(run)
                if len(counts) > MAX_MASK_RUNS:
                    raise PhalpTrackMaskError("PHALP mask exceeds bounded RLE complexity")
                current = bit
                run = 0
            run += 1
            if bit:
                pixel_count += 1
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    counts.append(run)
    if len(counts) > MAX_MASK_RUNS:
        raise PhalpTrackMaskError("PHALP mask exceeds bounded RLE complexity")
    if sum(counts) != width * height or pixel_count <= 0 or max_x < min_x or max_y < min_y:
        raise PhalpTrackMaskError("PHALP mask has invalid/empty RLE coverage")
    return counts, pixel_count, (min_x, min_y, max_x + 1, max_y + 1)


def mask_sha256(*, height: int, width: int, counts: Sequence[int]) -> str:
    payload = json.dumps(
        {"size": [height, width], "counts": list(counts)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def canonicalize_attested_track_masks(
    frame_results: Mapping[Any, Mapping[str, Any]],
    *,
    fps: float,
    source_index: int,
    selected_track_id: str,
    requested_timestamps_ms: Sequence[int],
    decode_mask: Callable[[object], object],
) -> dict[str, Any]:
    if not math.isfinite(fps) or fps <= 0.0 or fps > 1000.0:
        raise PhalpTrackMaskError("invalid source fps")
    if isinstance(source_index, bool) or not isinstance(source_index, int) or not 0 <= source_index <= 9999:
        raise PhalpTrackMaskError("source_index must be an integer in 0..9999")
    target = str(selected_track_id or "").strip()
    prefix = f"s{source_index:02d}-t"
    if not target.startswith(prefix) or len(target) <= len(prefix) or len(target) > 160:
        raise PhalpTrackMaskError("selected PHALP track id is invalid for source index")
    timestamps = _timestamps(requested_timestamps_ms)
    wanted = set(timestamps)
    found: dict[int, dict[str, Any]] = {}

    try:
        ordered = sorted(frame_results.values(), key=lambda frame: int(frame.get("time", -1)))
    except (TypeError, ValueError) as exc:
        raise PhalpTrackMaskError("PHALP frame time is invalid") from exc

    for frame in ordered:
        try:
            frame_index = int(frame["time"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PhalpTrackMaskError("PHALP frame is missing valid time") from exc
        if frame_index < 0:
            raise PhalpTrackMaskError("PHALP frame time must be non-negative")
        timestamp_ms = round(frame_index * 1000.0 / fps)
        if timestamp_ms not in wanted:
            continue
        try:
            tids = frame["tid"]
            ages = frame["tracked_time"]
            bboxes = frame["bbox"]
            masks = frame["mask"]
            confs = frame["conf"]
            sizes = frame["size"]
            item_count = len(tids)
        except (KeyError, TypeError) as exc:
            raise PhalpTrackMaskError("PHALP frame lacks mask-review history fields") from exc
        if not (item_count == len(ages) == len(bboxes) == len(masks) == len(confs) == len(sizes)):
            raise PhalpTrackMaskError("PHALP mask-review arrays are misaligned")

        matches: list[int] = []
        for index in range(item_count):
            try:
                age = int(ages[index])
            except (TypeError, ValueError):
                continue
            if age == 0 and f"s{source_index:02d}-t{tids[index]}" == target:
                matches.append(index)
        if len(matches) != 1:
            raise PhalpTrackMaskError(
                f"human-attested track is not exactly one observed detection at requested timestamp {timestamp_ms}"
            )
        if timestamp_ms in found:
            raise PhalpTrackMaskError("PHALP produced duplicate requested timestamp")
        index = matches[0]
        confidence = _finite(confs[index], label="PHALP mask confidence")
        if not 0.0 <= confidence <= 1.0:
            raise PhalpTrackMaskError("PHALP mask confidence must be in 0..1")
        try:
            size = sizes[index]
            height = int(size[0])
            width = int(size[1])
        except (TypeError, ValueError, IndexError) as exc:
            raise PhalpTrackMaskError("PHALP mask source-frame size is invalid") from exc
        if not 64 <= height <= 16384 or not 64 <= width <= 16384:
            raise PhalpTrackMaskError("PHALP mask source-frame dimensions are outside bounds")
        try:
            decoded = decode_mask(masks[index])
        except Exception as exc:
            raise PhalpTrackMaskError("PHALP instance mask could not be decoded") from exc
        normalized = _normalize_mask(decoded, expected_height=height, expected_width=width)
        counts, pixels, mask_box = _uncompressed_coco_rle(normalized)
        bbox = _bbox_tlwh(bboxes[index])
        digest = mask_sha256(height=height, width=width, counts=counts)
        found[timestamp_ms] = {
            "timestamp_ms": timestamp_ms,
            "confidence": round(confidence, 4),
            "bbox_tlwh": bbox,
            "frame_width": width,
            "frame_height": height,
            "mask_rle": {"size": [height, width], "counts": counts},
            "mask_sha256": digest,
            "mask_pixel_count": pixels,
            "mask_bbox_ltrb": list(mask_box),
        }

    missing = [timestamp for timestamp in timestamps if timestamp not in found]
    if missing:
        raise PhalpTrackMaskError(
            "human-reviewed PHALP timestamps are not all present as observed mask detections: "
            + ", ".join(str(item) for item in missing)
        )
    return {
        "format": FORMAT,
        "version": VERSION,
        "source_index": source_index,
        "selected_track_id": target,
        "requested_timestamps_ms": timestamps,
        "samples": [found[item] for item in timestamps],
        "all_samples_observed": True,
        "mask_type": "detectron2-coco-person-instance-mask",
        "mask_pixels_source_derived": True,
        "hidden_pixels_inferred": False,
        "generative_pixels_used": False,
        "human_identity_selection_required": True,
        "production_activation": False,
    }
