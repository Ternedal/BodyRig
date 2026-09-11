from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_unsupported_gesture_cannot_seed_amplitude_for_later_supported_gesture() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]

    assert "IsSupportedGestureId(_state.gesture.id)" in late_update
    unsupported = late_update.index("if (_state.gesture != null && !supportedGesture)")
    reset = late_update.index("_gestureAmplitude = 0.0f;", unsupported)
    smooth = late_update.index("_gestureAmplitude = Mathf.Lerp(_gestureAmplitude, targetGesture, blend);")
    realize = late_update.index("GestureRealized = ApplyGesture();")
    assert unsupported < reset < smooth < realize


def test_renderer_uses_one_supported_gesture_id_authority_for_smoothing_and_realization() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    helper = source[
        source.index("private static bool IsSupportedGestureId") : source.index("private bool HasSourceDerivedNaturalPosture")
    ]
    for gesture_id in ("small_shrug", "present", "neutral"):
        assert f'id == "{gesture_id}"' in helper

    apply_gesture = source[
        source.index("private bool ApplyGesture()") : source.index("private bool ApplyHeadMotion()")
    ]
    assert "!IsSupportedGestureId(_state.gesture.id)" in apply_gesture
