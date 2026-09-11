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

    runtime.apply_cue(BodyCue(utterance_id="u-no-emotion"))
    assert "expression" not in runtime.motor_state()


def test_missing_expression_releases_only_last_bodyrig_owned_affect() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    release = source[
        source.index("private void ReleaseOwnedExpression") : source.index("private bool ApplyExpression")
    ]

    assert "_lastOwnedExpressionEmotion" in release
    assert "_state.expression != null" in release
    assert "return;" in release
    for emotion, key in (
        ("neutral", "Neutral"),
        ("happy", "Happy"),
        ("angry", "Angry"),
        ("sad", "Sad"),
        ("relaxed", "Relaxed"),
        ("surprised", "Surprised"),
    ):
        assert f'case "{emotion}": expression.SetWeight(ExpressionKey.{key}, 0.0f); break;' in release
    for viseme in ("Aa", "Ih", "Ou", "Ee", "Oh"):
        assert f"ExpressionKey.{viseme}" not in release
    assert "_lastOwnedExpressionEmotion = null;" in release


def test_expression_realization_tracks_bodyrig_owned_affect_for_later_release() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]
    apply_expression = source[
        source.index("private bool ApplyExpression") : source.index("private bool ApplySpeech")
    ]

    assert "ReleaseOwnedExpression();" in late_update
    assert late_update.index("ReleaseOwnedExpression();") < late_update.index("ExpressionRealized = ApplyExpression();")
    assert "_lastOwnedExpressionEmotion = _state.expression.emotion;" in apply_expression


def test_expression_ownership_is_cleared_at_avatar_and_neutral_session_boundaries() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    bind = source[
        source.index("private void BindAvatarIfNeeded()") : source.index("private float LocomotionBlend")
    ]
    neutral = source[source.index("public void RestoreNeutralPose()") :]

    assert "_lastOwnedExpressionEmotion = null;" in bind
    assert "_lastOwnedExpressionEmotion = null;" in neutral
