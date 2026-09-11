from __future__ import annotations

import math
from typing import Any, Mapping

MIN_MOVEMENT_FRAMES = 24
MIN_MOVEMENT_SECONDS = 1.5
MIN_GAIT_STEP_EVENTS = 2
MIN_IDLE_SECONDS = 0.5

POSTURE_FIELDS = (
    "posture_torso_lean_degrees",
    "posture_shoulder_tilt_degrees",
    "posture_hip_tilt_degrees",
    "posture_head_offset_to_height",
)
GAIT_FIELDS = (
    "walk_cadence_spm",
    "stride_length_to_height",
    "stance_width_to_height",
    "vertical_bounce_to_height",
    "arm_swing_to_height",
    "arm_swing_asymmetry",
)
DYNAMICS_FIELDS = (
    "turn_speed",
    "turn_speed_degrees_per_second",
    "transition_intensity",
)
IDLE_FIELDS = ("idle_sway_to_height",)
COVERAGE_FIELDS = (
    "movement_observed_frames",
    "movement_observed_seconds",
    "gait_step_events",
    "idle_observed_seconds",
)
REQUIRED_FIELDS = frozenset((*POSTURE_FIELDS, *GAIT_FIELDS, *DYNAMICS_FIELDS, *IDLE_FIELDS, *COVERAGE_FIELDS))

FIELD_RANGES: dict[str, tuple[float, float]] = {
    "movement_observed_frames": (2.0, 1_000_000.0),
    "movement_observed_seconds": (0.0, 86_400.0),
    "gait_step_events": (0.0, 1_000_000.0),
    "idle_observed_seconds": (0.0, 86_400.0),
    "posture_torso_lean_degrees": (0.0, 90.0),
    "posture_shoulder_tilt_degrees": (0.0, 90.0),
    "posture_hip_tilt_degrees": (0.0, 90.0),
    "posture_head_offset_to_height": (0.0, 1.0),
    "walk_cadence_spm": (0.0, 300.0),
    "stride_length_to_height": (0.0, 2.0),
    "stance_width_to_height": (0.0, 1.0),
    "vertical_bounce_to_height": (0.0, 1.0),
    "arm_swing_to_height": (0.0, 2.0),
    "arm_swing_asymmetry": (0.0, 1.0),
    "turn_speed": (0.0, 1.0),
    "turn_speed_degrees_per_second": (0.0, 720.0),
    "transition_intensity": (0.0, 1.0),
    "idle_sway_to_height": (0.0, 1.0),
}
INTEGER_FIELDS = frozenset({"movement_observed_frames", "gait_step_events"})


class MovementIdentityError(ValueError):
    pass


def _number(value: object, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MovementIdentityError(f"movement identity field is not numeric: {field}")
    number = float(value)
    if not math.isfinite(number):
        raise MovementIdentityError(f"movement identity field is non-finite: {field}")
    lo, hi = FIELD_RANGES[field]
    if not lo <= number <= hi:
        raise MovementIdentityError(f"movement identity field is outside {lo}..{hi}: {field}")
    if field in INTEGER_FIELDS and (not isinstance(value, int) or isinstance(value, bool)):
        raise MovementIdentityError(f"movement identity field must be an integer: {field}")
    return number


def inspect_movement_identity(bodyprint: Mapping[str, Any]) -> dict[str, Any]:
    motion = bodyprint.get("motion")
    if not isinstance(motion, Mapping):
        return {
            "complete": False,
            "missing_fields": sorted(REQUIRED_FIELDS),
            "blockers": ["motion section is missing"],
        }

    present = set(motion)
    missing = sorted(REQUIRED_FIELDS - present)
    blockers: list[str] = []
    values: dict[str, float] = {}
    for field in sorted(REQUIRED_FIELDS & present):
        try:
            values[field] = _number(motion[field], field=field)
        except MovementIdentityError as exc:
            blockers.append(str(exc))

    frames = values.get("movement_observed_frames", 0.0)
    seconds = values.get("movement_observed_seconds", 0.0)
    steps = values.get("gait_step_events", 0.0)
    idle_seconds = values.get("idle_observed_seconds", 0.0)
    cadence = values.get("walk_cadence_spm")

    if "movement_observed_frames" in values and frames < MIN_MOVEMENT_FRAMES:
        blockers.append(f"movement coverage is too short: frames={int(frames)}/{MIN_MOVEMENT_FRAMES}")
    if "movement_observed_seconds" in values and seconds < MIN_MOVEMENT_SECONDS:
        blockers.append(f"movement coverage is too short: seconds={seconds:.3f}/{MIN_MOVEMENT_SECONDS:.3f}")
    if "gait_step_events" in values and steps < MIN_GAIT_STEP_EVENTS:
        blockers.append(f"gait evidence is incomplete: step_events={int(steps)}/{MIN_GAIT_STEP_EVENTS}")
    if "idle_observed_seconds" in values and idle_seconds < MIN_IDLE_SECONDS:
        blockers.append(f"idle evidence is incomplete: seconds={idle_seconds:.3f}/{MIN_IDLE_SECONDS:.3f}")
    if cadence is not None and not 30.0 <= cadence <= 240.0:
        blockers.append(f"observed gait cadence is implausible for identity authority: {cadence:.3f} spm")

    complete = not missing and not blockers
    return {
        "complete": complete,
        "missing_fields": missing,
        "blockers": blockers,
        "coverage": {
            "movement_observed_frames": int(frames) if "movement_observed_frames" in values else 0,
            "movement_observed_seconds": round(seconds, 3),
            "gait_step_events": int(steps) if "gait_step_events" in values else 0,
            "idle_observed_seconds": round(idle_seconds, 3),
        },
        "required_groups": {
            "posture": list(POSTURE_FIELDS),
            "gait": list(GAIT_FIELDS),
            "dynamics": list(DYNAMICS_FIELDS),
            "idle": list(IDLE_FIELDS),
        },
    }


def require_movement_identity(bodyprint: Mapping[str, Any]) -> dict[str, Any]:
    result = inspect_movement_identity(bodyprint)
    if result["complete"] is not True:
        details = [*result.get("missing_fields", []), *result.get("blockers", [])]
        suffix = "; ".join(str(item) for item in details) or "unknown movement identity blocker"
        raise MovementIdentityError(f"source-derived Movement Identity is incomplete: {suffix}")
    return result
