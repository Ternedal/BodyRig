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


class BodyprintExtractor:
    SHAPE_JOINTS = {"head", "left_shoulder", "right_shoulder", "left_hip", "right_hip", "left_wrist", "right_wrist", "left_ankle", "right_ankle"}

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

    def _motion(self, track: RecoveredTrack) -> dict[str, float]:
        velocities: list[float] = []
        heads: list[float] = []
        wrists: list[float] = []
        gestures = 0
        active = False
        usable_ms = 0
        for prev, curr in zip(track.frames, track.frames[1:]):
            dt = (curr.timestamp_ms - prev.timestamp_ms) / 1000.0
            if dt <= 0:
                continue
            height = self._height(curr)
            shared = set(prev.joints) & set(curr.joints)
            if height is None or height <= 1e-6 or not shared:
                continue
            usable_ms += curr.timestamp_ms - prev.timestamp_ms
            speed = sum(_distance(prev.joints[n], curr.joints[n]) / dt / height for n in shared) / len(shared)
            velocities.append(speed)
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
        out: dict[str, float] = {}
        if velocities:
            out["energy"] = _clamp01(sum(velocities) / len(velocities))
        if wrists:
            out["gesture_amplitude"] = _clamp01((sum(wrists) / len(wrists)) / 0.75)
        if usable_ms >= 1000:
            out["gesture_frequency"] = _clamp01((gestures / (usable_ms / 1000.0)) / 1.5)
        if heads:
            out["head_motion"] = _clamp01((sum(heads) / len(heads)) / 0.5)
        return out

    @staticmethod
    def _height(frame: RecoveryFrame) -> float | None:
        if not {"head", "left_ankle", "right_ankle"} <= set(frame.joints):
            return None
        return _distance(frame.joints["head"], _midpoint(frame.joints["left_ankle"], frame.joints["right_ankle"]))
