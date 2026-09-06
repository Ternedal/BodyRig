import pytest

from bodyrig.models import BodyCue, SpeechTiming
from bodyrig.runtime import BodyRuntime
from bodyrig.speech_timing_evidence import SpeechTimingEvidenceError, build_speech_timing_evidence


BODYPRINT = {
    "format": "modelrig-bodyprint",
    "version": 1,
    "motion": {"energy": 0.7, "head_motion": 0.8},
    "expression": {"gaze_strength": 0.75, "speech_motion": 0.8},
}


def _complete(runtime: BodyRuntime, utterance: str = "utt-1") -> None:
    runtime.apply_cue(BodyCue(utterance_id=utterance))
    runtime.apply_speech(SpeechTiming(utterance_id=utterance, state="start", elapsed_ms=0, amplitude=0.1))
    runtime.apply_speech(SpeechTiming(utterance_id=utterance, state="update", elapsed_ms=500, viseme="A", amplitude=0.4))
    runtime.apply_speech(SpeechTiming(utterance_id=utterance, state="stop", elapsed_ms=1000, amplitude=0.0))


def test_runtime_exposes_exact_completed_voicerig_timeline() -> None:
    runtime = BodyRuntime()
    runtime.activate("body-a", BODYPRINT)
    _complete(runtime)

    evidence = runtime.speech_timing_evidence()
    assert evidence == runtime.snapshot().speech_timing_evidence
    assert evidence["format"] == "bodyrig-speech-timing-evidence"
    assert evidence["version"] == 1
    assert evidence["utterance_id"] == "utt-1"
    assert evidence["source"] == "voicerig-runtime"
    assert evidence["events"] == [
        {"state": "start", "elapsed_ms": 0, "viseme": None, "amplitude": 0.1},
        {"state": "update", "elapsed_ms": 500, "viseme": "A", "amplitude": 0.4},
        {"state": "stop", "elapsed_ms": 1000, "viseme": None, "amplitude": 0.0},
    ]
    assert evidence["complete"] is True
    assert evidence["human_review_required"] is True
    assert evidence["production_activation"] is False


def test_new_cue_revokes_previous_timing_evidence() -> None:
    runtime = BodyRuntime()
    runtime.activate("body-a", BODYPRINT)
    _complete(runtime, "utt-old")
    assert runtime.speech_timing_evidence()["utterance_id"] == "utt-old"

    runtime.apply_cue(BodyCue(utterance_id="utt-new"))
    assert runtime.snapshot().speech_timing_evidence is None
    with pytest.raises(ValueError, match="no complete canonical"):
        runtime.speech_timing_evidence()


def test_body_switch_revokes_previous_timing_evidence() -> None:
    runtime = BodyRuntime()
    runtime.activate("body-a", BODYPRINT)
    _complete(runtime)
    runtime.activate("body-b", BODYPRINT)
    assert runtime.snapshot().speech_timing_evidence is None


def test_legacy_incomplete_sequence_animates_but_never_becomes_m4_evidence() -> None:
    runtime = BodyRuntime()
    runtime.activate("body-a", BODYPRINT)
    runtime.apply_cue(BodyCue(utterance_id="utt-legacy"))
    runtime.apply_speech(SpeechTiming(utterance_id="utt-legacy", state="update", elapsed_ms=500, amplitude=0.4))
    state = runtime.apply_speech(SpeechTiming(utterance_id="utt-legacy", state="stop", elapsed_ms=1000, amplitude=0.0))
    assert state.speech is not None
    assert state.speech_timing_evidence is None
    with pytest.raises(ValueError, match="no complete canonical"):
        runtime.speech_timing_evidence()


def test_evidence_builder_rejects_mixed_utterances() -> None:
    with pytest.raises(SpeechTimingEvidenceError, match="mix utterance ids"):
        build_speech_timing_evidence(
            [
                SpeechTiming(utterance_id="a", state="start", elapsed_ms=0),
                SpeechTiming(utterance_id="b", state="stop", elapsed_ms=100),
            ]
        )
