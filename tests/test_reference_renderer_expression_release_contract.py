from __future__ import annotations

from pathlib import Path

from bodyrig.models import BodyCue
from bodyrig.runtime import BodyRuntime


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_new_cue_without_emotion_produces_current_state_without_expression() -> None:
    runtime = BodyRuntime()
    runtime.activate("person-a", {"motion": {}, "expression": {}, "runtime": {}})
    runtime.apply_cue(BodyCue(utterance_id="u-emotion", emotion="happy"))
    assert runtime.motor_state()["expression"]["emotion"] == "happy"

    runtime.apply_cue(BodyCue(utterance_id="u-no-emotion", gaze="user"))
    motor = runtime.motor_state()
    assert "expression" not in motor
    assert motor["gaze"]["target"] == "user"


def test_missing_or_unrealizable_expression_releases_only_if_last_bodyrig_weight_is_still_present() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    release = source[
        source.index("private void ReleaseOwnedExpression") : source.index("private bool ApplyExpression")
    ]

    assert "private static bool IsSupportedExpressionEmotion" in source
    assert "_lastOwnedExpressionEmotion" in release
    assert "_lastOwnedExpressionWeight" in release
    assert "_state.expression != null && IsSupportedExpressionEmotion(_state.expression.emotion)" in release
    assert "SameExpressionWeight" in release
    for emotion, key in (
        ("neutral", "Neutral"),
        ("happy", "Happy"),
        ("angry", "Angry"),
        ("sad", "Sad"),
        ("relaxed", "Relaxed"),
        ("surprised", "Surprised"),
    ):
        assert f'case "{emotion}":' in release
        assert f"expression.GetWeight(ExpressionKey.{key})" in release
        assert f"expression.SetWeight(ExpressionKey.{key}, 0.0f);" in release
    for viseme in ("Aa", "Ih", "Ou", "Ee", "Oh"):
        assert f"ExpressionKey.{viseme}" not in release
    assert "_lastOwnedExpressionEmotion = null;" in release
    assert "_lastOwnedExpressionWeight = 0.0f;" in release


def test_supported_expression_state_keeps_ownership_but_unsupported_state_does_not() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    helper = source[
        source.index("private static bool IsSupportedExpressionEmotion") :
        source.index("private static bool IsSupportedSpeechViseme")
    ]
    release = source[
        source.index("private void ReleaseOwnedExpression") : source.index("private bool ApplyExpression")
    ]

    for emotion in ("neutral", "happy", "angry", "sad", "relaxed", "surprised"):
        assert f'case "{emotion}":' in helper
    assert "return true;" in helper
    assert "default:" in helper
    assert "return false;" in helper
    assert "_state.expression != null && IsSupportedExpressionEmotion(_state.expression.emotion)" in release
    assert "if (_state.expression != null ||" not in release


def test_expression_realization_tracks_bodyrig_owned_affect_for_later_release() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]
    apply_expression = source[
        source.index("private bool ApplyExpression") : source.index("private void ReleaseOwnedSpeechViseme")
    ]

    assert "ReleaseOwnedExpression();" in late_update
    assert late_update.index("ReleaseOwnedExpression();") < late_update.index("ExpressionRealized = ApplyExpression();")
    assert "_lastOwnedExpressionEmotion = _state.expression.emotion;" in apply_expression
    assert "_lastOwnedExpressionWeight = weight;" in apply_expression


def test_expression_ownership_is_cleared_at_avatar_and_neutral_session_boundaries() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    bind = source[
        source.index("private void BindAvatarIfNeeded()") : source.index("private float LocomotionBlend")
    ]
    neutral = source[source.index("public void RestoreNeutralPose()") :]

    assert "_lastOwnedExpressionEmotion = null;" in bind
    assert "_lastOwnedExpressionWeight = 0.0f;" in bind
    assert "_lastOwnedExpressionEmotion = null;" in neutral
    assert "_lastOwnedExpressionWeight = 0.0f;" in neutral
