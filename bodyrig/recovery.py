from __future__ import annotations

import json
import math
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol, Sequence

Vec3 = tuple[float, float, float]


@dataclass(frozen=True)
class RecoveryFrame:
    timestamp_ms: int
    joints: Mapping[str, Vec3]
    confidence: float = 1.0


@dataclass(frozen=True)
class RecoveredTrack:
    track_id: str
    frames: Sequence[RecoveryFrame]


@dataclass(frozen=True)
class RecoveryResult:
    tracks: Sequence[RecoveredTrack]
    adapter: str
    revision: str


class RecoveryAdapter(Protocol):
    name: str
    revision: str
    def recover(self, sources: Sequence[Path]) -> RecoveryResult: ...


class RecoveryError(RuntimeError):
    pass


def _finite_vec(value: object, field: str) -> Vec3:
    if not isinstance(value, list) or len(value) != 3:
        raise RecoveryError(f"{field}: expected [x,y,z]")
    out: list[float] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not math.isfinite(float(item)):
            raise RecoveryError(f"{field}: coordinates must be finite numbers")
        out.append(float(item))
    return out[0], out[1], out[2]


def parse_recovery_result(payload: object, *, expected_adapter: str | None = None) -> RecoveryResult:
    if not isinstance(payload, dict):
        raise RecoveryError("recovery result must be an object")
    if set(payload) != {"format", "version", "adapter", "revision", "tracks"}:
        raise RecoveryError("recovery result fields must match v1 exactly")
    if payload["format"] != "bodyrig-recovery" or payload["version"] != 1:
        raise RecoveryError("unsupported recovery format/version")
    adapter = payload["adapter"]
    revision = payload["revision"]
    if not isinstance(adapter, str) or not adapter or len(adapter) > 80:
        raise RecoveryError("invalid adapter id")
    if expected_adapter is not None and adapter != expected_adapter:
        raise RecoveryError("adapter identity mismatch")
    if not isinstance(revision, str) or len(revision) > 160 or not revision:
        raise RecoveryError("invalid adapter revision")
    raw_tracks = payload["tracks"]
    if not isinstance(raw_tracks, list) or not 1 <= len(raw_tracks) <= 64:
        raise RecoveryError("tracks must contain 1..64 tracks")
    tracks: list[RecoveredTrack] = []
    ids: set[str] = set()
    for ti, raw_track in enumerate(raw_tracks):
        if not isinstance(raw_track, dict) or set(raw_track) != {"track_id", "frames"}:
            raise RecoveryError(f"tracks[{ti}]: invalid object")
        track_id = raw_track["track_id"]
        if not isinstance(track_id, str) or not track_id or len(track_id) > 160 or track_id in ids:
            raise RecoveryError(f"tracks[{ti}]: invalid/duplicate track_id")
        ids.add(track_id)
        raw_frames = raw_track["frames"]
        if not isinstance(raw_frames, list) or not 2 <= len(raw_frames) <= 1_000_000:
            raise RecoveryError(f"tracks[{ti}]: frames must contain at least two frames")
        frames: list[RecoveryFrame] = []
        previous_ts = -1
        for fi, raw_frame in enumerate(raw_frames):
            if not isinstance(raw_frame, dict) or set(raw_frame) - {"timestamp_ms", "confidence", "joints"} or not {"timestamp_ms", "joints"} <= set(raw_frame):
                raise RecoveryError(f"tracks[{ti}].frames[{fi}]: invalid object")
            timestamp = raw_frame["timestamp_ms"]
            if isinstance(timestamp, bool) or not isinstance(timestamp, int) or timestamp < 0 or timestamp <= previous_ts:
                raise RecoveryError(f"tracks[{ti}]: timestamps must be strictly increasing non-negative integers")
            previous_ts = timestamp
            confidence = raw_frame.get("confidence", 1.0)
            if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not math.isfinite(float(confidence)) or not 0.0 <= float(confidence) <= 1.0:
                raise RecoveryError(f"tracks[{ti}].frames[{fi}]: invalid confidence")
            raw_joints = raw_frame["joints"]
            if not isinstance(raw_joints, dict) or not raw_joints or len(raw_joints) > 256:
                raise RecoveryError(f"tracks[{ti}].frames[{fi}]: invalid joints")
            joints = {name: _finite_vec(point, f"joint {name}") for name, point in raw_joints.items() if isinstance(name, str) and 0 < len(name) <= 80}
            if len(joints) != len(raw_joints):
                raise RecoveryError("invalid joint name")
            frames.append(RecoveryFrame(timestamp_ms=timestamp, joints=joints, confidence=float(confidence)))
        tracks.append(RecoveredTrack(track_id=track_id, frames=tuple(frames)))
    return RecoveryResult(tracks=tuple(tracks), adapter=adapter, revision=revision)


class JsonCommandRecoveryAdapter:
    """Runs a heavy recovery engine in an isolated process/environment."""

    def __init__(self, command: Sequence[str], *, name: str, revision: str, timeout_seconds: int = 3600) -> None:
        if not command:
            raise ValueError("command is required")
        self.command = tuple(command)
        self.name = name
        self.revision = revision
        self.timeout_seconds = timeout_seconds

    def recover(self, sources: Sequence[Path]) -> RecoveryResult:
        if not 1 <= len(sources) <= 10:
            raise RecoveryError("BodyRig V1 accepts 1..10 source clips")
        request = {"format": "bodyrig-recovery-request", "version": 1, "sources": [str(path.resolve()) for path in sources]}
        try:
            completed = subprocess.run(self.command, input=json.dumps(request), text=True, capture_output=True, timeout=self.timeout_seconds, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RecoveryError("recovery adapter failed to execute") from exc
        if completed.returncode != 0:
            raise RecoveryError(f"recovery adapter exited {completed.returncode}: {completed.stderr.strip()[-2000:]}")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RecoveryError("recovery adapter returned invalid JSON") from exc
        result = parse_recovery_result(payload, expected_adapter=self.name)
        if result.revision != self.revision:
            raise RecoveryError("recovery adapter revision mismatch")
        return result


def _distance(a: Vec3, b: Vec3) -> float:
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def _midpoint(a: Vec3, b: Vec3) -> Vec3:
    return tuple((a[i] + b[i]) / 2.0 for i in range(3))  # type: ignore[return-value]


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _percentile(values: Sequence[float], quantile: float) -> float:
    ordered = sorted(float(item) for item in values)
    if not ordered:
        raise ValueError("percentile requires at least one value")
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * quantile
    lo = int(math.floor(index))
    hi = int(math.ceil(index))
    if lo == hi:
        return ordered[lo]
    weight = index - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _median(values: Sequence[float]) -> float:
    return _percentile(values, 0.5)


def _axis_delta(a: float, b: float) -> float:
    """Smallest difference between unoriented shoulder axes (period pi)."""
    return (b - a + math.pi / 2.0) % math.pi - math.pi / 2.0


def _continuous_segments(frames: Sequence[RecoveryFrame]) -> list[list[RecoveryFrame]]:
    """Split actual observations at gaps so missing PHALP frames never become coverage."""
    if len(frames) < 2:
        return []
    deltas = [
        curr.timestamp_ms - prev.timestamp_ms
        for prev, curr in zip(frames, frames[1:])
        if curr.timestamp_ms > prev.timestamp_ms
    ]
    if not deltas:
        return []
    nominal_ms = _percentile([float(value) for value in deltas], 0.25)
    # Normal video should provide substantially denser observations than 4 Hz.
    # The hard 250 ms ceiling keeps sparse/occluded endpoints fail-closed even
    # when every remaining delta is large and would otherwise define itself as
    # the apparent sampling cadence.
    maximum_gap_ms = min(250.0, max(100.0, nominal_ms * 2.5))

    segments: list[list[RecoveryFrame]] = []
    current = [frames[0]]
    for prev, curr in zip(frames, frames[1:]):
        delta_ms = curr.timestamp_ms - prev.timestamp_ms
        if 0 < delta_ms <= maximum_gap_ms:
            current.append(curr)
        else:
            if len(current) >= 2:
                segments.append(current)
            current = [curr]
    if len(current) >= 2:
        segments.append(current)
    return segments


class BodyprintExtractor:
    SHAPE_JOINTS = {"head", "left_shoulder", "right_shoulder", "left_hip", "right_hip", "left_wrist", "right_wrist", "left_ankle", "right_ankle"}
    POSTURE_JOINTS = {"head", "left_shoulder", "right_shoulder", "left_hip", "right_hip", "left_ankle", "right_ankle"}
    GAIT_JOINTS = {"left_shoulder", "right_shoulder", "left_hip", "right_hip", "left_wrist", "right_wrist", "left_ankle", "right_ankle"}

    def extract(self, track: RecoveredTrack) -> dict:
        if len(track.frames) < 2:
            raise RecoveryError("track needs at least two frames")
        result: dict = {"format": "modelrig-bodyprint", "version": 1}
        shape = self._shape(track)
        motion = self._motion(track)
        if shape:
            result["shape"] = shape
        if motion:
            result["motion"] = motion
        if len(result) == 2:
            raise RecoveryError("track contains insufficient joints for a bodyprint")
        return result

    def _shape(self, track: RecoveredTrack) -> dict[str, float]:
        samples: list[tuple[float, float, float, float]] = []
        for frame in track.frames:
            if frame.confidence < 0.5 or not self.SHAPE_JOINTS <= set(frame.joints):
                continue
            j = frame.joints
            ankle_mid = _midpoint(j["left_ankle"], j["right_ankle"])
            height = _distance(j["head"], ankle_mid)
            if height <= 1e-6:
                continue
            shoulder = _distance(j["left_shoulder"], j["right_shoulder"]) / height
            hip = _distance(j["left_hip"], j["right_hip"]) / height
            arm = (_distance(j["left_shoulder"], j["left_wrist"]) + _distance(j["right_shoulder"], j["right_wrist"])) / (2 * height)
            hip_mid = _midpoint(j["left_hip"], j["right_hip"])
            leg = (_distance(hip_mid, j["left_ankle"]) + _distance(hip_mid, j["right_ankle"])) / (2 * height)
            samples.append((shoulder, hip, arm, leg))
        if not samples:
            return {}
        samples.sort(key=sum)
        middle = samples[len(samples) // 2]
        return {"shoulder_to_height": _clamp01(middle[0]), "hip_to_height": _clamp01(middle[1]), "arm_to_height": _clamp01(middle[2]), "leg_to_height": _clamp01(middle[3])}

    def _motion(self, track: RecoveredTrack) -> dict[str, float | int]:
        usable_frames = [
            frame
            for frame in track.frames
            if frame.confidence >= 0.5 and self._height(frame) not in (None, 0.0)
        ]
        segments = _continuous_segments(usable_frames)
        velocities: list[tuple[int, int, float, float]] = []
        heads: list[float] = []
        wrists: list[float] = []
        gestures = 0
        usable_ms = 0
        for segment_id, segment in enumerate(segments):
            active = False
            for prev, curr in zip(segment, segment[1:]):
                dt = (curr.timestamp_ms - prev.timestamp_ms) / 1000.0
                if dt <= 0:
                    continue
                height = self._height(curr)
                shared = set(prev.joints) & set(curr.joints)
                if height is None or height <= 1e-6 or not shared:
                    continue
                delta_ms = curr.timestamp_ms - prev.timestamp_ms
                usable_ms += delta_ms
                speed = sum(_distance(prev.joints[n], curr.joints[n]) / dt / height for n in shared) / len(shared)
                velocities.append((segment_id, curr.timestamp_ms, speed, dt))
                if "head" in shared:
                    heads.append(_distance(prev.joints["head"], curr.joints["head"]) / dt / height)
                if {"left_shoulder", "right_shoulder"} <= set(curr.joints):
                    shoulder_mid = _midpoint(curr.joints["left_shoulder"], curr.joints["right_shoulder"])
                    vals = [_distance(curr.joints[w], shoulder_mid) / height for w in ("left_wrist", "right_wrist") if w in curr.joints]
                    if vals:
                        amp = sum(vals) / len(vals)
                        wrists.append(amp)
                        now = amp > 0.35 and speed > 0.15
                        if now and not active:
                            gestures += 1
                        active = now

        out: dict[str, float | int] = {}
        speed_values = [item[2] for item in velocities]
        if speed_values:
            out["energy"] = _clamp01(sum(speed_values) / len(speed_values))
        if wrists:
            out["gesture_amplitude"] = _clamp01((sum(wrists) / len(wrists)) / 0.75)
        if usable_ms >= 1000:
            out["gesture_frequency"] = _clamp01((gestures / (usable_ms / 1000.0)) / 1.5)
        if heads:
            out["head_motion"] = _clamp01((sum(heads) / len(heads)) / 0.5)

        observed_frames = sum(len(segment) for segment in segments)
        if observed_frames:
            out["movement_observed_frames"] = observed_frames
        if usable_ms > 0:
            out["movement_observed_seconds"] = round(usable_ms / 1000.0, 3)

        posture_rows: list[dict[str, float | int]] = []
        gait_rows: list[dict[str, float | int]] = []
        for segment_id, segment in enumerate(segments):
            for frame in segment:
                height = self._height(frame)
                if height is None or height <= 1e-6:
                    continue
                joints = frame.joints
                if self.POSTURE_JOINTS <= set(joints):
                    left_shoulder = joints["left_shoulder"]
                    right_shoulder = joints["right_shoulder"]
                    left_hip = joints["left_hip"]
                    right_hip = joints["right_hip"]
                    shoulder_mid = _midpoint(left_shoulder, right_shoulder)
                    hip_mid = _midpoint(left_hip, right_hip)
                    lateral_x = right_shoulder[0] - left_shoulder[0]
                    lateral_z = right_shoulder[2] - left_shoulder[2]
                    lateral_norm = math.hypot(lateral_x, lateral_z)
                    if lateral_norm > 1e-6:
                        lateral = (lateral_x / lateral_norm, lateral_z / lateral_norm)
                        forward = (-lateral[1], lateral[0])
                        torso_delta = (shoulder_mid[0] - hip_mid[0], shoulder_mid[2] - hip_mid[2])
                        head_delta = (joints["head"][0] - shoulder_mid[0], joints["head"][2] - shoulder_mid[2])
                        torso_horizontal = math.hypot(torso_delta[0], torso_delta[1])
                        torso_vertical = abs(shoulder_mid[1] - hip_mid[1])
                        shoulder_horizontal = lateral_norm
                        hip_horizontal = math.hypot(right_hip[0] - left_hip[0], right_hip[2] - left_hip[2])
                        head_horizontal = math.hypot(head_delta[0], head_delta[1])
                        torso_forward = torso_delta[0] * forward[0] + torso_delta[1] * forward[1]
                        torso_right = torso_delta[0] * lateral[0] + torso_delta[1] * lateral[1]
                        head_forward = head_delta[0] * forward[0] + head_delta[1] * forward[1]
                        head_right = head_delta[0] * lateral[0] + head_delta[1] * lateral[1]
                        posture_rows.append({
                            "segment": segment_id,
                            "timestamp_ms": float(frame.timestamp_ms),
                            "torso_lean": math.degrees(math.atan2(torso_horizontal, max(torso_vertical, 1e-6))),
                            "torso_forward_lean": math.degrees(math.atan2(torso_forward, max(torso_vertical, 1e-6))),
                            "torso_right_lean": math.degrees(math.atan2(torso_right, max(torso_vertical, 1e-6))),
                            "shoulder_tilt": math.degrees(math.atan2(abs(right_shoulder[1] - left_shoulder[1]), max(shoulder_horizontal, 1e-6))),
                            "shoulder_roll": math.degrees(math.atan2(right_shoulder[1] - left_shoulder[1], max(shoulder_horizontal, 1e-6))),
                            "hip_tilt": math.degrees(math.atan2(abs(right_hip[1] - left_hip[1]), max(hip_horizontal, 1e-6))),
                            "hip_roll": math.degrees(math.atan2(right_hip[1] - left_hip[1], max(hip_horizontal, 1e-6))),
                            "head_offset": min(1.0, head_horizontal / height),
                            "head_forward_offset": max(-1.0, min(1.0, head_forward / height)),
                            "head_right_offset": max(-1.0, min(1.0, head_right / height)),
                            "torso_offset": min(1.0, torso_horizontal / height),
                        })

                if self.GAIT_JOINTS <= set(joints):
                    left_shoulder = joints["left_shoulder"]
                    right_shoulder = joints["right_shoulder"]
                    lateral_x = right_shoulder[0] - left_shoulder[0]
                    lateral_z = right_shoulder[2] - left_shoulder[2]
                    lateral_norm = math.hypot(lateral_x, lateral_z)
                    if lateral_norm <= 1e-6:
                        continue
                    lateral = (lateral_x / lateral_norm, lateral_z / lateral_norm)
                    forward = (-lateral[1], lateral[0])
                    left_ankle = joints["left_ankle"]
                    right_ankle = joints["right_ankle"]
                    ankle_delta = (left_ankle[0] - right_ankle[0], left_ankle[2] - right_ankle[2])
                    left_wrist_delta = (joints["left_wrist"][0] - left_shoulder[0], joints["left_wrist"][2] - left_shoulder[2])
                    right_wrist_delta = (joints["right_wrist"][0] - right_shoulder[0], joints["right_wrist"][2] - right_shoulder[2])
                    hip_mid = _midpoint(joints["left_hip"], joints["right_hip"])
                    gait_rows.append({
                        "segment": segment_id,
                        "timestamp_ms": float(frame.timestamp_ms),
                        "forward_gap": (ankle_delta[0] * forward[0] + ankle_delta[1] * forward[1]) / height,
                        "stance_width": abs(ankle_delta[0] * lateral[0] + ankle_delta[1] * lateral[1]) / height,
                        "hip_y": hip_mid[1] / height,
                        "left_arm": (left_wrist_delta[0] * forward[0] + left_wrist_delta[1] * forward[1]) / height,
                        "right_arm": (right_wrist_delta[0] * forward[0] + right_wrist_delta[1] * forward[1]) / height,
                        "orientation": math.atan2(lateral[1], lateral[0]),
                    })

        if len(posture_rows) >= 3:
            out["posture_torso_lean_degrees"] = round(_median([float(row["torso_lean"]) for row in posture_rows]), 4)
            out["posture_torso_forward_lean_degrees"] = round(_median([float(row["torso_forward_lean"]) for row in posture_rows]), 4)
            out["posture_torso_right_lean_degrees"] = round(_median([float(row["torso_right_lean"]) for row in posture_rows]), 4)
            out["posture_shoulder_tilt_degrees"] = round(_median([float(row["shoulder_tilt"]) for row in posture_rows]), 4)
            out["posture_shoulder_roll_degrees"] = round(_median([float(row["shoulder_roll"]) for row in posture_rows]), 4)
            out["posture_hip_tilt_degrees"] = round(_median([float(row["hip_tilt"]) for row in posture_rows]), 4)
            out["posture_hip_roll_degrees"] = round(_median([float(row["hip_roll"]) for row in posture_rows]), 4)
            out["posture_head_offset_to_height"] = round(_median([float(row["head_offset"]) for row in posture_rows]), 4)
            out["posture_head_forward_offset_to_height"] = round(_median([float(row["head_forward_offset"]) for row in posture_rows]), 4)
            out["posture_head_right_offset_to_height"] = round(_median([float(row["head_right_offset"]) for row in posture_rows]), 4)

        if len(gait_rows) >= 2:
            turn_speeds: list[float] = []
            gait_intervals: list[float] = []
            total_events = 0
            for segment_id in range(len(segments)):
                rows = [row for row in gait_rows if row["segment"] == segment_id]
                for prev, curr in zip(rows, rows[1:]):
                    dt = (float(curr["timestamp_ms"]) - float(prev["timestamp_ms"])) / 1000.0
                    if dt > 0:
                        turn_speeds.append(abs(math.degrees(_axis_delta(float(prev["orientation"]), float(curr["orientation"])))) / dt)

                states: list[tuple[int, int]] = []
                for row in rows:
                    signal = float(row["forward_gap"])
                    state = 1 if signal >= 0.025 else (-1 if signal <= -0.025 else 0)
                    if state:
                        states.append((int(float(row["timestamp_ms"])), state))
                events: list[int] = []
                last_state = 0
                last_event = -10_000
                for timestamp, state in states:
                    if last_state and state != last_state and timestamp - last_event >= 200:
                        events.append(timestamp)
                        last_event = timestamp
                    last_state = state
                total_events += len(events)
                gait_intervals.extend((b - a) / 1000.0 for a, b in zip(events, events[1:]) if b > a)

            if turn_speeds:
                turn_dps = min(720.0, _percentile(turn_speeds, 0.5))
                out["turn_speed_degrees_per_second"] = round(turn_dps, 4)
                out["turn_speed"] = round(_clamp01(turn_dps / 180.0), 4)

            out["gait_step_events"] = total_events
            if total_events >= 2 and gait_intervals:
                cadence = 60.0 / _median(gait_intervals)
                if 30.0 <= cadence <= 240.0:
                    out["walk_cadence_spm"] = round(cadence, 3)
                    out["stride_length_to_height"] = round(min(2.0, _percentile([abs(float(row["forward_gap"])) for row in gait_rows], 0.9)), 4)
                    out["stance_width_to_height"] = round(min(1.0, _median([float(row["stance_width"]) for row in gait_rows])), 4)
                    hip_y = [float(row["hip_y"]) for row in gait_rows]
                    out["vertical_bounce_to_height"] = round(min(1.0, max(0.0, _percentile(hip_y, 0.9) - _percentile(hip_y, 0.1))), 4)
                    left_arm = [float(row["left_arm"]) for row in gait_rows]
                    right_arm = [float(row["right_arm"]) for row in gait_rows]
                    left_amp = max(0.0, _percentile(left_arm, 0.9) - _percentile(left_arm, 0.1))
                    right_amp = max(0.0, _percentile(right_arm, 0.9) - _percentile(right_arm, 0.1))
                    out["arm_swing_to_height"] = round(min(2.0, (left_amp + right_amp) / 2.0), 4)
                    denominator = max(left_amp, right_amp, 1e-6)
                    out["arm_swing_asymmetry"] = round(_clamp01(abs(left_amp - right_amp) / denominator), 4)
        elif segments:
            out["gait_step_events"] = 0

        transition_values: list[float] = []
        for segment_id in range(len(segments)):
            segment_speeds = [item[2] for item in velocities if item[0] == segment_id]
            transition_values.extend(abs(curr - prev) for prev, curr in zip(segment_speeds, segment_speeds[1:]))
        if transition_values:
            out["transition_intensity"] = round(_clamp01(_median(transition_values) / 0.5), 4)

        speed_by_key = {(segment_id, timestamp): (speed, dt) for segment_id, timestamp, speed, dt in velocities}
        idle_rows = [
            row
            for row in posture_rows
            if (int(row["segment"]), int(float(row["timestamp_ms"]))) in speed_by_key
            and speed_by_key[(int(row["segment"]), int(float(row["timestamp_ms"])) )][0] <= 0.12
        ]
        idle_seconds = sum(
            speed_by_key[(int(row["segment"]), int(float(row["timestamp_ms"])) )][1]
            for row in idle_rows
        )
        out["idle_observed_seconds"] = round(idle_seconds, 3)
        if idle_seconds >= 0.5 and len(idle_rows) >= 2:
            offsets = [float(row["torso_offset"]) for row in idle_rows]
            out["idle_sway_to_height"] = round(min(1.0, max(0.0, _percentile(offsets, 0.9) - _percentile(offsets, 0.1))), 4)
        return out

    @staticmethod
    def _height(frame: RecoveryFrame) -> float | None:
        if not {"head", "left_ankle", "right_ankle"} <= set(frame.joints):
            return None
        return _distance(frame.joints["head"], _midpoint(frame.joints["left_ankle"], frame.joints["right_ankle"]))