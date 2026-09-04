import pytest
from pydantic import ValidationError

from bodyrig.models import BodyCue, SpeechTiming
from bodyrig.runtime import BodyRuntime


LOW_MOTION = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "motion": {"energy": 0.2, "gesture_amplitude": 0.15, "head_motion": 0.1},
    "expression": {"gaze_strength": 0.3, "speech_motion": 0.2},
    "runtime": {"gesture_intensity": 0.3},
}
HIGH_MOTION = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "motion": {"energy": 0.8, "gesture_amplitude": 0.9, "head_motion": 0.85},
    "expression": {"gaze_strength": 0.8, "speech_motion": 0.9},
    "runtime": {"gesture_intensity": 0.9},
}


def test_bodycue_fails_closed_on_unknown_field():
    with pytest.raises(ValidationError):
        BodyCue.model_validate({
            "type": "modelrig-body-cue",
            "version": 1,
            "utterance_id": "u-1",
            "emotion": "thoughtful",
            "raw_bone_rotation": 42,
        })


def test_bodycue_requires_semantic_instruction():
    with pytest.raises(ValidationError, match="semantic"):
        BodyCue(utterance_id="u-empty")


def test_runtime_rejects_stale_voice_timing():
    runtime = BodyRuntime()
    runtime.apply_cue(BodyCue(utterance_id="u-new", emotion="thoughtful"))
    with pytest.raises(ValueError, match="does not match"):
        runtime.apply_speech(SpeechTiming(utterance_id="u-old", state="start"))


def test_runtime_keeps_semantic_cue():
    runtime = BodyRuntime()
    state = runtime.apply_cue(
        BodyCue(
            utterance_id="u-1",
            emotion="amused",
            intensity=0.4,
            gesture="small_shrug",
            gaze="user",
        )
    )
    assert state.cue["gesture"] == "small_shrug" and state.utterance_id == "u-1"


def test_same_cue_is_personalized_by_active_bodyprint():
    cue = BodyCue(
        utterance_id="u-personal",
        intensity=0.6,
        energy=0.5,
        gesture="small_shrug",
        gaze="user",
    )

    quiet = BodyRuntime()
    quiet.activate("quiet-body", LOW_MOTION)
    quiet.apply_cue(cue)
    quiet_motor = quiet.motor_state()

    expressive = BodyRuntime()
    expressive.activate("expressive-body", HIGH_MOTION)
    expressive.apply_cue(cue)
    expressive_motor = expressive.motor_state()

    assert quiet_motor["gesture"]["id"] == expressive_motor["gesture"]["id"] == "small_shrug"
    assert expressive_motor["gesture"]["amplitude"] > quiet_motor["gesture"]["amplitude"]
    assert expressive_motor["motion"]["head_motion"] > quiet_motor["motion"]["head_motion"]
    assert expressive_motor["gaze"]["strength"] > quiet_motor["gaze"]["strength"]


def test_voice_amplitude_is_resolved_through_body_expression_style():
    cue = BodyCue(utterance_id="u-speech", emotion="amused")
    timing = SpeechTiming(utterance_id="u-speech", state="update", elapsed_ms=120, viseme="aa", amplitude=0.5)

    quiet = BodyRuntime()
    quiet.activate("quiet-body", LOW_MOTION)
    quiet.apply_cue(cue)
    quiet.apply_speech(timing)

    expressive = BodyRuntime()
    expressive.activate("expressive-body", HIGH_MOTION)
    expressive.apply_cue(cue)
    expressive.apply_speech(timing)

    assert expressive.motor_state()["speech"]["amplitude"] > quiet.motor_state()["speech"]["amplitude"]


def test_body_switch_clears_stale_utterance_and_timing():
    runtime = BodyRuntime()
    runtime.activate("one", LOW_MOTION)
    runtime.apply_cue(BodyCue(utterance_id="u-old", emotion="thoughtful"))
    runtime.apply_speech(SpeechTiming(utterance_id="u-old", state="start"))

    state = runtime.activate("two", HIGH_MOTION)
    assert state.utterance_id is None
    assert state.cue is None
    assert state.speech is None
    with pytest.raises(ValueError, match="no active BodyCue"):
        runtime.motor_state()


def test_explicit_body_id_must_match_active_body():
    runtime = BodyRuntime()
    runtime.activate("body-a", LOW_MOTION)
    with pytest.raises(ValueError, match="does not match"):
        runtime.apply_cue(BodyCue(utterance_id="u-1", body_id="body-b"))
