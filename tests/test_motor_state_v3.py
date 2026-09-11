from copy import deepcopy

import pytest
from pydantic import ValidationError

from bodyrig.models import BodyCue, BodyCueV2, LocomotionCue
from bodyrig.runtime import BodyRuntime


FULL_MOVEMENT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "motion": {
        "energy": 0.72,
        "gesture_frequency": 0.81,
        "gesture_amplitude": 0.63,
        "head_motion": 0.58,
        "turn_speed": 0.44,
        "walk_cadence_spm": 116.0,
        "movement_observed_frames": 60,
        "movement_observed_seconds": 4.5,
        "gait_step_events": 7,
        "idle_observed_seconds": 0.9,
        "posture_torso_lean_degrees": 5.2,
        "posture_shoulder_tilt_degrees": 1.3,
        "posture_hip_tilt_degrees": 0.8,
        "posture_head_offset_to_height": 0.041,
        "stride_length_to_height": 0.34,
        "stance_width_to_height": 0.13,
        "vertical_bounce_to_height": 0.024,
        "arm_swing_to_height": 0.19,
        "arm_swing_asymmetry": 0.07,
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


def test_bodycue_v2_allows_locomotion_as_the_only_semantic_action() -> None:
    cue = BodyCueV2(
        utterance_id="u-walk",
        locomotion=LocomotionCue(action="walk"),
    )
    assert cue.version == 2
    assert cue.locomotion is not None
    assert cue.locomotion.action == "walk"
    assert cue.locomotion.effort is None


def test_bodycue_v1_stays_frozen_and_rejects_locomotion() -> None:
    with pytest.raises(ValidationError):
        BodyCue.model_validate(
            {
                "type": "modelrig-body-cue",
                "version": 1,
                "utterance_id": "u-old",
                "locomotion": {"action": "walk"},
            }
        )


def test_v2_cue_cannot_be_silently_downgraded_to_motor_v1_or_v2() -> None:
    runtime = BodyRuntime()
    runtime.activate("person-a", FULL_MOVEMENT)
    runtime.apply_cue(BodyCueV2(utterance_id="u-walk", locomotion=LocomotionCue(action="walk")))

    with pytest.raises(ValueError, match="requires Motor State v3"):
        runtime.motor_state()
    with pytest.raises(ValueError, match="requires Motor State v3"):
        runtime.motor_state_v2()


def test_v3_natural_walk_uses_source_derived_movement_identity() -> None:
    runtime = BodyRuntime()
    runtime.activate("person-a", FULL_MOVEMENT)
    runtime.apply_cue(BodyCueV2(utterance_id="u-walk", locomotion=LocomotionCue(action="walk")))

    state = runtime.motor_state_v3()

    assert state["version"] == 3
    assert state["locomotion"] == {
        "action": "walk",
        "effort": 0.5,
        "transition_intensity": 0.31,
        "cadence_spm": 116.0,
        "stride_length_to_height": 0.34,
        "stance_width_to_height": 0.13,
        "vertical_bounce_to_height": 0.024,
        "arm_swing_to_height": 0.19,
    }
    assert state["embodiment"]["observed"]["walk_cadence_spm"] == 116.0
    assert state["embodiment"]["observed"]["stride_length_to_height"] == 0.34


def test_v3_brisk_walk_scales_around_observed_identity_not_generic_defaults() -> None:
    runtime = BodyRuntime()
    runtime.activate("person-a", FULL_MOVEMENT)
    runtime.apply_cue(
        BodyCueV2(
            utterance_id="u-brisk",
            locomotion=LocomotionCue(action="walk", effort=1.0),
        )
    )

    locomotion = runtime.motor_state_v3()["locomotion"]
    assert locomotion["cadence_spm"] == 145.0
    assert locomotion["stride_length_to_height"] == 0.391
    assert locomotion["stance_width_to_height"] == 0.13
    assert locomotion["vertical_bounce_to_height"] == 0.0276
    assert locomotion["arm_swing_to_height"] == 0.2185
    assert locomotion["transition_intensity"] == 0.31


def test_v3_turn_uses_observed_turn_speed_and_explicit_direction() -> None:
    runtime = BodyRuntime()
    runtime.activate("person-a", FULL_MOVEMENT)
    runtime.apply_cue(
        BodyCueV2(
            utterance_id="u-turn",
            locomotion=LocomotionCue(action="turn_left"),
        )
    )

    assert runtime.motor_state_v3()["locomotion"] == {
        "action": "turn_left",
        "effort": 0.5,
        "transition_intensity": 0.31,
        "turn_speed_degrees_per_second": 79.2,
    }


def test_v3_locomotion_fails_closed_without_complete_movement_identity() -> None:
    incomplete = deepcopy(FULL_MOVEMENT)
    del incomplete["motion"]["stance_width_to_height"]
    runtime = BodyRuntime()
    runtime.activate("person-a", incomplete)
    runtime.apply_cue(BodyCueV2(utterance_id="u-walk", locomotion=LocomotionCue(action="walk")))

    with pytest.raises(ValueError, match="requires complete source-derived Movement Identity"):
        runtime.motor_state_v3()


def test_v3_turn_fails_closed_when_observed_turn_speed_is_zero() -> None:
    no_turn = deepcopy(FULL_MOVEMENT)
    no_turn["motion"]["turn_speed_degrees_per_second"] = 0.0
    no_turn["motion"]["turn_speed"] = 0.0
    runtime = BodyRuntime()
    runtime.activate("person-a", no_turn)
    runtime.apply_cue(BodyCueV2(utterance_id="u-turn", locomotion=LocomotionCue(action="turn_right")))

    with pytest.raises(ValueError, match="non-zero source-derived turn-speed evidence"):
        runtime.motor_state_v3()


def test_v3_turn_rejects_positive_speed_that_rounds_to_zero() -> None:
    tiny_turn = deepcopy(FULL_MOVEMENT)
    tiny_turn["motion"]["turn_speed_degrees_per_second"] = 0.00001
    tiny_turn["motion"]["turn_speed"] = 0.00001
    runtime = BodyRuntime()
    runtime.activate("person-a", tiny_turn)
    runtime.apply_cue(BodyCueV2(utterance_id="u-turn-tiny", locomotion=LocomotionCue(action="turn_left")))

    with pytest.raises(ValueError, match="Motor State v3 precision"):
        runtime.motor_state_v3()


def test_v3_never_creates_locomotion_from_movement_identity_alone() -> None:
    runtime = BodyRuntime()
    runtime.activate("person-a", FULL_MOVEMENT)
    runtime.apply_cue(BodyCue(utterance_id="u-talk", emotion="neutral"))

    v2 = runtime.motor_state_v2()
    v3 = runtime.motor_state_v3()

    expected = deepcopy(v2)
    expected["version"] = 3
    assert v3 == expected
    assert "locomotion" not in v3
