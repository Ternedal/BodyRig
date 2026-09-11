from copy import deepcopy

from bodyrig.models import BodyCue
from bodyrig.runtime import BodyRuntime


FULL_STYLE = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "motion": {
        "energy": 0.72,
        "gesture_frequency": 0.81,
        "gesture_amplitude": 0.63,
        "head_motion": 0.58,
        "turn_speed": 0.44,
        "walk_cadence_spm": 116.0,
        "posture_torso_lean_degrees": 5.2,
        "posture_torso_forward_lean_degrees": 4.8,
        "posture_torso_right_lean_degrees": -1.2,
        "posture_shoulder_tilt_degrees": 1.3,
        "posture_shoulder_roll_degrees": -1.3,
        "posture_hip_tilt_degrees": 0.8,
        "posture_hip_roll_degrees": -0.8,
        "posture_head_offset_to_height": 0.041,
        "posture_head_forward_offset_to_height": 0.036,
        "posture_head_right_offset_to_height": 0.019,
        "stride_length_to_height": 0.34,
        "stance_width_to_height": 0.13,
        "vertical_bounce_to_height": 0.024,
        "left_arm_swing_to_height": 0.18,
        "right_arm_swing_to_height": 0.20,
        "arm_swing_to_height": 0.19,
        "arm_swing_asymmetry": 0.10,
        "turn_speed_degrees_per_second": 79.2,
        "transition_intensity": 0.31,
        "idle_sway_to_height": 0.012,
    },
    "expression": {
        "blink_rate_per_min": 17.0,
        "gaze_strength": 0.76,
        "head_tilt": 0.36,
        "speech_motion": 0.69,
    },
    "runtime": {
        "idle_strength": 0.42,
        "gaze_smoothing": 0.67,
        "gesture_intensity": 0.74,
        "breathing_strength": 0.31,
    },
}


def _cue() -> BodyCue:
    return BodyCue(
        utterance_id="u-embodiment",
        emotion="amused",
        intensity=0.6,
        energy=0.5,
        gesture="small_shrug",
        gaze="user",
        posture="relaxed",
        duration_ms=900,
    )


def test_v2_preserves_v1_performed_state_and_adds_observed_receipt() -> None:
    runtime = BodyRuntime()
    runtime.activate("person-a", FULL_STYLE)
    runtime.apply_cue(_cue())

    v1 = runtime.motor_state()
    v2 = runtime.motor_state_v2()

    assert v1["version"] == 1
    assert "embodiment" not in v1
    performed_v2 = deepcopy(v2)
    performed_v2.pop("embodiment")
    performed_v2["version"] = 1
    assert performed_v2 == v1

    assert v2["version"] == 2
    assert v2["embodiment"] == {
        "source": "modelrig-bodyprint-v1",
        "observed": {
            "energy": 0.72,
            "gesture_frequency": 0.81,
            "gesture_amplitude": 0.63,
            "head_motion": 0.58,
            "turn_speed": 0.44,
            "walk_cadence_spm": 116.0,
            "posture_torso_lean_degrees": 5.2,
            "posture_torso_forward_lean_degrees": 4.8,
            "posture_torso_right_lean_degrees": -1.2,
            "posture_shoulder_tilt_degrees": 1.3,
            "posture_shoulder_roll_degrees": -1.3,
            "posture_hip_tilt_degrees": 0.8,
            "posture_hip_roll_degrees": -0.8,
            "posture_head_offset_to_height": 0.041,
            "posture_head_forward_offset_to_height": 0.036,
            "posture_head_right_offset_to_height": 0.019,
            "stride_length_to_height": 0.34,
            "stance_width_to_height": 0.13,
            "vertical_bounce_to_height": 0.024,
            "left_arm_swing_to_height": 0.18,
            "right_arm_swing_to_height": 0.20,
            "arm_swing_to_height": 0.19,
            "arm_swing_asymmetry": 0.10,
            "turn_speed_degrees_per_second": 79.2,
            "transition_intensity": 0.31,
            "idle_sway_to_height": 0.012,
            "blink_rate_per_min": 17.0,
            "gaze_strength": 0.76,
            "head_tilt": 0.36,
            "speech_motion": 0.69,
            "idle_strength": 0.42,
            "gaze_smoothing": 0.67,
            "gesture_intensity": 0.74,
            "breathing_strength": 0.31,
        },
    }


def test_v2_never_turns_v1_defaults_into_personal_observations() -> None:
    sparse = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {"energy": 0.2},
    }
    runtime = BodyRuntime()
    runtime.activate("person-a", sparse)
    runtime.apply_cue(BodyCue(utterance_id="u-sparse", emotion="thoughtful"))

    v1 = runtime.motor_state()
    v2 = runtime.motor_state_v2()

    # V1 keeps its historical neutral fallbacks for performed values.
    assert v1["motion"]["head_motion"] == 0.2
    # V2 may expose only the field that was actually present in BodyPrint.
    assert v2["embodiment"]["observed"] == {"energy": 0.2}
    assert "gesture_frequency" not in v2["embodiment"]["observed"]
    assert "walk_cadence_spm" not in v2["embodiment"]["observed"]
    assert "stride_length_to_height" not in v2["embodiment"]["observed"]
    assert "left_arm_swing_to_height" not in v2["embodiment"]["observed"]
    assert "right_arm_swing_to_height" not in v2["embodiment"]["observed"]
    assert "posture_torso_forward_lean_degrees" not in v2["embodiment"]["observed"]
    assert "blink_rate_per_min" not in v2["embodiment"]["observed"]


def test_v2_omits_embodiment_when_bodyprint_has_no_observed_behavior() -> None:
    shape_only = {
        "format": "modelrig-bodyprint",
        "version": 1,
        "shape": {"height_scale": 1.0},
    }
    runtime = BodyRuntime()
    runtime.activate("person-a", shape_only)
    runtime.apply_cue(BodyCue(utterance_id="u-shape", emotion="neutral"))

    state = runtime.motor_state_v2()
    assert state["version"] == 2
    assert "embodiment" not in state
