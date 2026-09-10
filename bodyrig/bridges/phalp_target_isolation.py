from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from .phalp_track_review import PhalpTrackReviewError, _bbox_tlwh, _finite, canonicalize_phalp_track_review

FORMAT = "bodyrig-phalp-target-isolation"
VERSION = 1
DEFAULT_MAX_ISOLATION_SAMPLES = 24
MAX_ISOLATION_SAMPLES = 48
MIN_TARGET_OBSERVATIONS = 3
HIGH_OVERLAP_THRESHOLD = 0.10
SEVERE_OVERLAP_THRESHOLD = 0.30


class PhalpTargetIsolationError(ValueError):
    pass


def _area(box: list[float]) -> float:
    return max(0.0, box[2]) * max(0.0, box[3])


def _target_overlap_fraction(target: list[float], other: list[float]) -> float:
    tx, ty, tw, th = target
    ox, oy, ow, oh = other
    left = max(tx, ox)
    top = max(ty, oy)
    right = min(tx + tw, ox + ow)
    bottom = min(ty + th, oy + oh)
    overlap = max(0.0, right - left) * max(0.0, bottom - top)
    denominator = _area(target)
    return overlap / denominator if denominator > 0.0 else 0.0


def _sample_evenly(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if len(rows) <= count:
        return [dict(row) for row in rows]
    if count == 1:
        return [dict(rows[len(rows) // 2])]
    indices = {
        int(round(index * (len(rows) - 1) / float(count - 1)))
        for index in range(count)
    }
    return [dict(rows[index]) for index in sorted(indices)]


def _nearest_rank_p95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, math.ceil(0.95 * len(ordered)) - 1))
    return ordered[index]


def canonicalize_target_isolation(
    frame_results: Mapping[Any, Mapping[str, Any]],
    *,
    fps: float,
    source_index: int,
    selected_track_id: str,
    min_confidence: float = 0.25,
    max_samples: int = DEFAULT_MAX_ISOLATION_SAMPLES,
) -> dict[str, Any]:
    """Derive source-grounded isolation samples for a human-attested PHALP track.

    Identity authority is external: this function follows exactly one supplied
    track id and never chooses the target. Only observed PHALP states
    (tracked_time == 0) contribute. Other observed tracks are used solely to
    quantify possible cross-person overlap with the selected target box.
    """

    if isinstance(max_samples, bool) or not isinstance(max_samples, int) or not 3 <= max_samples <= MAX_ISOLATION_SAMPLES:
        raise PhalpTargetIsolationError(f"max_samples must be in 3..{MAX_ISOLATION_SAMPLES}")
    selected_track_id = str(selected_track_id or "").strip()
    expected_prefix = f"s{source_index:02d}-t"
    if not selected_track_id.startswith(expected_prefix) or len(selected_track_id) > 160:
        raise PhalpTargetIsolationError("selected track id does not belong to the requested source")

    try:
        review = canonicalize_phalp_track_review(
            frame_results,
            fps=fps,
            source_index=source_index,
            min_confidence=min_confidence,
        )
    except PhalpTrackReviewError as exc:
        raise PhalpTargetIsolationError(str(exc)) from exc
    review_rows = [row for row in review["tracks"] if row.get("track_id") == selected_track_id]
    if len(review_rows) != 1:
        raise PhalpTargetIsolationError("human-attested track is not uniquely reproducible in PHALP review output")
    canonical_review_track = dict(review_rows[0])

    try:
        ordered = sorted(frame_results.values(), key=lambda frame: int(frame.get("time", -1)))
    except (TypeError, ValueError) as exc:
        raise PhalpTargetIsolationError("PHALP frame time is invalid") from exc

    states: list[dict[str, Any]] = []
    seen_timestamps: set[int] = set()
    for frame in ordered:
        try:
            frame_index = int(frame["time"])
            tids = frame["tid"]
            tracked_time = frame["tracked_time"]
            bboxes = frame["bbox"]
            item_count = len(tids)
        except (KeyError, TypeError, ValueError) as exc:
            raise PhalpTargetIsolationError("PHALP frame is missing target-isolation fields") from exc
        if frame_index < 0 or not (item_count == len(tracked_time) == len(bboxes)):
            raise PhalpTargetIsolationError("PHALP target-isolation arrays are invalid")
        confs = frame.get("conf", [1.0] * item_count)
        timestamp_ms = round(frame_index * 1000.0 / fps)

        observed: list[tuple[str, float, list[float]]] = []
        for index in range(item_count):
            try:
                age = int(tracked_time[index])
                confidence = _finite(confs[index], label="PHALP confidence") if index < len(confs) else 1.0
                bbox = _bbox_tlwh(bboxes[index])
            except (TypeError, ValueError, IndexError, PhalpTrackReviewError):
                continue
            if age != 0 or confidence < min_confidence:
                continue
            track_id = f"s{source_index:02d}-t{tids[index]}"
            observed.append((track_id, confidence, bbox))

        target_rows = [item for item in observed if item[0] == selected_track_id]
        if not target_rows:
            continue
        if len(target_rows) != 1:
            raise PhalpTargetIsolationError("selected track appears more than once in one observed PHALP frame")
        if timestamp_ms in seen_timestamps:
            raise PhalpTargetIsolationError("selected track produced a duplicate isolation timestamp")
        seen_timestamps.add(timestamp_ms)
        _, target_confidence, target_bbox = target_rows[0]
        others = [bbox for track_id, _, bbox in observed if track_id != selected_track_id]
        overlaps = [_target_overlap_fraction(target_bbox, other_bbox) for other_bbox in others]
        states.append(
            {
                "timestamp_ms": timestamp_ms,
                "confidence": round(max(0.0, min(1.0, target_confidence)), 4),
                "bbox_tlwh": target_bbox,
                "observed_other_track_count": len(others),
                "max_other_overlap_fraction": round(max(overlaps, default=0.0), 6),
            }
        )

    if len(states) < MIN_TARGET_OBSERVATIONS:
        raise PhalpTargetIsolationError(
            f"human-attested track has only {len(states)} observed states; need at least {MIN_TARGET_OBSERVATIONS}"
        )
    states.sort(key=lambda row: int(row["timestamp_ms"]))
    overlap_values = [float(row["max_other_overlap_fraction"]) for row in states]
    samples = _sample_evenly(states, max_samples)

    return {
        "format": FORMAT,
        "version": VERSION,
        "source_index": source_index,
        "selected_track_id": selected_track_id,
        "identity_authority": "human-track-attestation",
        "canonical_review_track": canonical_review_track,
        "observed_state_count": len(states),
        "first_timestamp_ms": int(states[0]["timestamp_ms"]),
        "last_timestamp_ms": int(states[-1]["timestamp_ms"]),
        "max_other_overlap_fraction": round(max(overlap_values, default=0.0), 6),
        "p95_other_overlap_fraction": round(_nearest_rank_p95(overlap_values), 6),
        "high_overlap_state_count": sum(value > HIGH_OVERLAP_THRESHOLD for value in overlap_values),
        "severe_overlap_state_count": sum(value > SEVERE_OVERLAP_THRESHOLD for value in overlap_values),
        "isolation_samples": samples,
        "machine_identity_selection": False,
        "biometric_identity_inference_used": False,
        "generic_guessing_permitted": False,
        "target_isolated_source_authority": False,
        "photoidentity_source_evidence_authority": False,
        "reconstruction_permitted": False,
        "production_activation": False,
    }
