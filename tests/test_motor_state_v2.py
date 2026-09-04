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
