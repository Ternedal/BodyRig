from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Mapping, Sequence

# 4D-Humans' HMR2 SMPL wrapper maps its first 25 returned joints to the
# OpenPose BODY_25 order. BodyRig only consumes the stable subset needed for
# portable proportions/motion features.
OPENPOSE25_TO_BODYRIG = {
    "head": 0,            # Nose is used as the head reference, not absolute head top.
    "right_shoulder": 2,
    "right_wrist": 4,
    "left_shoulder": 5,
    "left_wrist": 7,
    "right_hip": 9,
    "right_ankle": 11,
    "left_hip": 12,
    "left_ankle": 14,
}


class PhalpConversionError(ValueError):
    pass


def _finite_point(value: Any) -> list[float] | None:
    try:
        if len(value) < 3:
            return None
        point = [float(value[0]), float(value[1]), float(value[2])]
    except (TypeError, ValueError, IndexError):
        return None
    if not all(math.isfinite(item) for item in point):
        return None
    return point


def _canonical_joints(joints: Any) -> dict[str, list[float]] | None:
    try:
        if len(joints) < 25:
            return None
    except TypeError:
        return None
    result: dict[str, list[float]] = {}
    for name, index in OPENPOSE25_TO_BODYRIG.items():
        point = _finite_point(joints[index])
        if point is None:
            return None
        result[name] = point
    return result


def canonicalize_phalp_results(
    frame_results: Mapping[Any, Mapping[str, Any]],
    *,
    fps: float,
    source_index: int,
    min_confidence: float = 0.25,
) -> list[dict[str, Any]]:
    """Convert one PHALP result dictionary to BodyRig recovery tracks.

    Only actual observations (`tracked_time == 0`) are retained. Predicted
    track states across occlusion are useful to PHALP, but BodyRig must not
    mistake them for observed source motion when building a bodyprint.
    """
    if not math.isfinite(fps) or fps <= 0.0 or fps > 1000.0:
        raise PhalpConversionError("invalid source fps")
    if source_index < 0:
        raise PhalpConversionError("source_index must be non-negative")

    by_track: dict[str, list[dict[str, Any]]] = defaultdict(list)
    ordered = sorted(frame_results.values(), key=lambda frame: int(frame.get("time", -1)))
    last_timestamp: dict[str, int] = {}

    for frame in ordered:
        try:
            frame_index = int(frame["time"])
            tids: Sequence[Any] = frame["tid"]
            tracked_time: Sequence[Any] = frame["tracked_time"]
            joints_list: Sequence[Any] = frame["3d_joints"]
        except (KeyError, TypeError, ValueError) as exc:
            raise PhalpConversionError("PHALP frame is missing required tracking fields") from exc
        confs: Sequence[Any] = frame.get("conf", [1.0] * len(tids))
        if not (len(tids) == len(tracked_time) == len(joints_list)):
            raise PhalpConversionError("PHALP frame arrays are misaligned")

        timestamp_ms = round(frame_index * 1000.0 / fps)
        for index, raw_tid in enumerate(tids):
            try:
                age = int(tracked_time[index])
                confidence = float(confs[index]) if index < len(confs) else 1.0
            except (TypeError, ValueError, IndexError):
                continue
            if age != 0 or not math.isfinite(confidence) or confidence < min_confidence:
                continue
            joints = _canonical_joints(joints_list[index])
            if joints is None:
                continue
            track_id = f"s{source_index:02d}-t{raw_tid}"
            if last_timestamp.get(track_id, -1) >= timestamp_ms:
                continue
            last_timestamp[track_id] = timestamp_ms
            by_track[track_id].append({
                "timestamp_ms": timestamp_ms,
                "confidence": max(0.0, min(1.0, confidence)),
                "joints": joints,
            })

    return [
        {"track_id": track_id, "frames": frames}
        for track_id, frames in sorted(by_track.items())
        if len(frames) >= 2
    ]
