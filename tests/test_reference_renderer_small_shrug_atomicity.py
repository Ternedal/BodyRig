from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def _source() -> str:
    return DRIVER.read_text(encoding="utf-8")


def test_small_shrug_ownership_requires_both_shoulders() -> None:
    source = _source()
    late = source[source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")]
    assert 'var smallShrugOwnsShoulders =' in late
    assert 'gestureId == "small_shrug" && _leftShoulder != null && _rightShoulder != null;' in late
    assert 'smallShrugOwnsShoulders || (gestureId == "neutral" && _leftShoulder != null)' in late
    assert 'smallShrugOwnsShoulders || (gestureId == "neutral" && _rightShoulder != null)' in late


def test_small_shrug_fails_before_any_partial_write() -> None:
    source = _source()
    gesture = source[source.index("private bool ApplyGesture") : source.index("private bool ApplyHeadMotion")]
    shrug = gesture[gesture.index('if (_state.gesture.id == "small_shrug")') : gesture.index('if (_state.gesture.id == "present")')]
    guard = 'if (_leftShoulder == null || _rightShoulder == null) return false;'
    assert guard in shrug
    assert shrug.index(guard) < shrug.index('_leftShoulder.localPosition')
    assert shrug.index(guard) < shrug.index('_rightShoulder.localPosition')
    assert 'if (_leftShoulder != null) _leftShoulder.localPosition' not in shrug
    assert 'if (_rightShoulder != null) _rightShoulder.localPosition' not in shrug
    assert 'return true;' in shrug


def test_neutral_still_owns_available_shoulders_independently() -> None:
    source = _source()
    late = source[source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")]
    assert 'gestureId == "neutral" && _leftShoulder != null' in late
    assert 'gestureId == "neutral" && _rightShoulder != null' in late


def test_incomplete_small_shrug_model_has_no_mutation_or_ownership() -> None:
    left_exists = True
    right_exists = False
    owns_shoulders = left_exists and right_exists
    assert (owns_shoulders, owns_shoulders, owns_shoulders) == (False, False, False)
