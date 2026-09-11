from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_missing_or_stopped_speech_releases_head_motion_boost_immediately() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]

    guard = 'if (_state.speech == null || _state.speech.state == "stop")'
    assert guard in late_update
    release_start = late_update.index(guard)
    head_motion = late_update.index("MotionRealized = ApplyHeadMotion();")
    release = late_update[release_start:head_motion]
    assert "_speechAmplitude = 0.0f;" in release
    assert "_speechAmplitude = Mathf.Lerp(_speechAmplitude, targetSpeech, blend);" in late_update
    assert release_start < head_motion


def test_active_speech_still_uses_smoothed_amplitude() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]

    guard = late_update.index('if (_state.speech == null || _state.speech.state == "stop")')
    smooth = late_update.index("_speechAmplitude = Mathf.Lerp(_speechAmplitude, targetSpeech, blend);")
    assert guard < smooth

    head_motion = source[
        source.index("private bool ApplyHeadMotion") : source.index("private bool ApplyGaze")
    ]
    assert "var speechBoost = 1.0f + 0.35f * _speechAmplitude;" in head_motion
