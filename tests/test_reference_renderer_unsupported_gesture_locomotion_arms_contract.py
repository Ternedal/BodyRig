from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_unsupported_gesture_does_not_steal_locomotion_arm_ownership() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    right_pose = source[
        source.index("private static bool GestureOwnsRightArmPose") :
        source.index("private static bool GestureOwnsLeftUpperArm")
    ]
    right_adapter = source[
        source.index("private static bool GestureOwnsRightUpperArm") :
        source.index("private bool HasSourceDerivedNaturalPosture")
    ]
    locomotion = source[
        source.index("private bool ApplyLocomotion") : source.index("private bool ApplyGesture")
    ]

    assert "gesture == null || !IsSupportedGestureId(gesture.id)" in right_pose
    assert "return false;" in right_pose
    assert "return GestureOwnsRightArmPose(gesture);" in right_adapter
    assert "!GestureOwnsLeftUpperArm(_state.gesture)" in locomotion
    assert "!GestureOwnsRightUpperArm(_state.gesture)" in locomotion


def test_supported_gesture_arm_precedence_matches_actual_bone_ownership() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    supported = source[
        source.index("private static bool IsSupportedGestureId") :
        source.index("private static bool GestureOwnsLeftUpperArm")
    ]
    for gesture_id in ("small_shrug", "present", "neutral"):
        assert f'id == "{gesture_id}"' in supported

    left = source[
        source.index("private static bool GestureOwnsLeftUpperArm") :
        source.index("private static bool GestureOwnsRightUpperArm")
    ]
    right_pose = source[
        source.index("private static bool GestureOwnsRightArmPose") :
        source.index("private static bool GestureOwnsLeftUpperArm")
    ]

    assert 'gesture.id == "small_shrug"' not in left
    assert 'gesture.id == "small_shrug"' not in right_pose
    assert 'gesture.id == "present"' in right_pose
    assert 'gesture.id == "neutral"' in right_pose
