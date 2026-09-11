from __future__ import annotations

from pathlib import Path

from bodyrig.models import BodyCue, SpeechTiming
from bodyrig.runtime import BodyRuntime


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_new_cue_replaces_active_speech_and_omits_speech_from_motor_state() -> None:
    runtime = BodyRuntime()
    runtime.activate("person-a", {"motion": {}, "expression": {}, "runtime": {}})
    runtime.apply_cue(BodyCue(utterance_id="u-speech", emotion="happy"))
    runtime.apply_speech(
        SpeechTiming(
            utterance_id="u-speech",
            state="update",
            elapsed_ms=120,
            viseme="aa",
            amplitude=0.6,
        )
    )
    assert runtime.motor_state()["speech"]["viseme"] == "aa"

    runtime.apply_cue(BodyCue(utterance_id="u-next", gaze="user"))
    assert "speech" not in runtime.motor_state()


def test_missing_speech_releases_only_bodyrig_owned_viseme_channel() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    release = source[
        source.index("private void ReleaseOwnedSpeechViseme") : source.index("private bool ApplySpeech")
    ]

    assert "_speechVisemeOwned" in release
    assert "_state.speech != null" in release
    for viseme in ("Aa", "Ih", "Ou", "Ee", "Oh"):
        assert f"ExpressionKey.{viseme}" in release
    for affect in ("Neutral", "Happy", "Angry", "Sad", "Relaxed", "Surprised"):
        assert f"ExpressionKey.{affect}" not in release
    assert "_speechVisemeOwned = false;" in release


def test_speech_realization_tracks_and_releases_viseme_ownership() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]
    apply_speech = source[
        source.index("private bool ApplySpeech") : source.index("private void RestoreGesturePose")
    ]

    assert "ReleaseOwnedSpeechViseme();" in late_update
    assert late_update.index("ReleaseOwnedSpeechViseme();") < late_update.index("SpeechTimingRealized = ApplySpeech();")
    assert "_speechVisemeOwned = true;" in apply_speech
    assert "_speechVisemeOwned = false;" in apply_speech


def test_speech_viseme_ownership_is_cleared_at_session_boundaries() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    bind = source[
        source.index("private void BindAvatarIfNeeded()") : source.index("private float LocomotionBlend")
    ]
    neutral = source[source.index("public void RestoreNeutralPose()") :]

    assert "_speechVisemeOwned = false;" in bind
    assert "_speechVisemeOwned = false;" in neutral
