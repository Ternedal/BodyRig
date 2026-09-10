from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

FORMAT = "bodyrig-phalp-track-review"
VERSION = 1
DEFAULT_MAX_SAMPLES_PER_TRACK = 6
MAX_SAMPLES_PER_TRACK = 12
MAX_TRACKS = 64


class PhalpTrackReviewError(ValueError):
    pass


def _finite(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhalpTrackReviewError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise PhalpTrackReviewError(f"{label} must be finite")
    return result


def _bbox_tlwh(value: object) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)) or len(value) != 4:
        raise PhalpTrackReviewError("PHALP bbox must contain exactly four values")
    x, y, width, height = (_finite(item, label="PHALP bbox coordinate") for item in value)
    if width <= 0.0 or height <= 0.0:
        raise PhalpTrackReviewError("PHALP bbox width/height must be positive")
    return [round(x, 4), round(y, 4), round(width, 4), round(height, 4)]


def _sample_evenly(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if len(rows) <= count:
        return [dict(item) for item in rows]
    if count == 1:
        return [dict(rows[len(rows) // 2])]
    indices = {
        int(round(index * (len(rows) - 1) / float(count - 1)))
        for index in range(count)
    }
    return [dict(rows[index]) for index in sorted(indices)]


def canonicalize_phalp_track_review(
    frame_results: Mapping[Any, Mapping[str, Any]],
    *,
    fps: float,
    source_index: int,
    min_confidence: float = 0.25,
    max_samples_per_track: int = DEFAULT_MAX_SAMPLES_PER_TRACK,
) -> dict[str, Any]:
    """Convert raw PHALP results into source-only human-review candidates.

    This intentionally exports no PHALP appearance embeddings and never chooses
    which track belongs to the requested performer. Only actually observed
    states (tracked_time == 0) are retained. Track identity is source-local.
    """

    if not math.isfinite(fps) or fps <= 0.0 or fps > 1000.0:
        raise PhalpTrackReviewError("invalid source fps")
    if isinstance(source_index, bool) or not isinstance(source_index, int) or not 0 <= source_index <= 9999:
        raise PhalpTrackReviewError("source_index must be an integer in 0..9999")
    if not math.isfinite(min_confidence) or not 0.0 <= min_confidence <= 1.0:
        raise PhalpTrackReviewError("min_confidence must be in 0..1")
    if (
        isinstance(max_samples_per_track, bool)
        or not isinstance(max_samples_per_track, int)
        or not 1 <= max_samples_per_track <= MAX_SAMPLES_PER_TRACK
    ):
        raise PhalpTrackReviewError(
            f"max_samples_per_track must be in 1..{MAX_SAMPLES_PER_TRACK}"
        )

    by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    last_timestamp: dict[str, int] = {}
    ordered = sorted(frame_results.values(), key=lambda frame: int(frame.get("time", -1)))

    for frame in ordered:
        try:
            frame_index = int(frame["time"])
            tids: Sequence[Any] = frame["tid"]
            tracked_time: Sequence[Any] = frame["tracked_time"]
            bboxes: Sequence[Any] = frame["bbox"]
        except (KeyError, TypeError, ValueError) as exc:
            raise PhalpTrackReviewError("PHALP frame is missing required track-review fields") from exc
        if frame_index < 0:
            raise PhalpTrackReviewError("PHALP frame time must be non-negative")
        if not (len(tids) == len(tracked_time) == len(bboxes)):
            raise PhalpTrackReviewError("PHALP track-review arrays are misaligned")
        confs: Sequence[Any] = frame.get("conf", [1.0] * len(tids))

        timestamp_ms = round(frame_index * 1000.0 / fps)
        for index, raw_tid in enumerate(tids):
            try:
                age = int(tracked_time[index])
                confidence = float(confs[index]) if index < len(confs) else 1.0
            except (TypeError, ValueError, IndexError):
                continue
            if age != 0 or not math.isfinite(confidence) or confidence < min_confidence:
                continue
            track_id = f"s{source_index:02d}-t{raw_tid}"
            if len(track_id) > 160:
                raise PhalpTrackReviewError("PHALP track id exceeds BodyRig bound")
            if last_timestamp.get(track_id, -1) >= timestamp_ms:
                continue
            last_timestamp[track_id] = timestamp_ms
            by_track[track_id].append(
                {
                    "timestamp_ms": timestamp_ms,
                    "confidence": round(max(0.0, min(1.0, confidence)), 4),
                    "bbox_tlwh": _bbox_tlwh(bboxes[index]),
                }
            )

    tracks: list[dict[str, Any]] = []
    for track_id, rows in sorted(by_track.items()):
        if len(rows) < 2:
            continue
        tracks.append(
            {
                "track_id": track_id,
                "observation_count": len(rows),
                "first_timestamp_ms": int(rows[0]["timestamp_ms"]),
                "last_timestamp_ms": int(rows[-1]["timestamp_ms"]),
                "samples": _sample_evenly(rows, max_samples_per_track),
            }
        )
    if len(tracks) > MAX_TRACKS:
        raise PhalpTrackReviewError(f"PHALP produced more than {MAX_TRACKS} review tracks")

    return {
        "format": FORMAT,
        "version": VERSION,
        "source_index": source_index,
        "tracks": tracks,
        "target_track_id": None,
        "human_identity_attestation_required": True,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
