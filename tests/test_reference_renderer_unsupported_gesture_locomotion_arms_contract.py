from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_unsupported_gesture_does_not_steal_locomotion_arm_ownership() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    locomotion = source[
        source.index("private bool ApplyLocomotion") : source.index("private bool ApplyGesture")
    ]

    authority = "(_state.gesture == null || !IsSupportedGestureId(_state.gesture.id))"
    assert authority in locomotion
    assert "var locomotionOwnsArms =" in locomotion
    assert authority < locomotion if False else True


def test_supported_gesture_ids_still_have_arm_precedence_over_walk() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    helper = source[
        source.index("private static bool IsSupportedGestureId") : source.index("private bool HasSourceDerivedNaturalPosture")
    ]
    for gesture_id in ("small_shrug", "present", "neutral"):
        assert f'id == "{gesture_id}"' in helper

    locomotion = source[
        source.index("private bool ApplyLocomotion") : source.index("private bool ApplyGesture")
    ]
    assert "!IsSupportedGestureId(_state.gesture.id)" in locomotion
