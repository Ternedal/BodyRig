from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_walk_tracks_arm_ownership_per_anatomical_side() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    locomotion = source[source.index("private bool ApplyLocomotion") : source.index("private bool ApplyGesture")]

    assert "private bool _locomotionLeftArmPoseOwnedLastFrame;" in source
    assert "private bool _locomotionRightArmPoseOwnedLastFrame;" in source
    assert "_locomotionArmPoseOwnedLastFrame" not in source

    assert "var locomotionOwnsLeftArm" in locomotion
    assert "var locomotionOwnsRightArm" in locomotion
    assert "if (locomotionOwnsLeftArm)" in locomotion
    assert "if (locomotionOwnsRightArm)" in locomotion
    assert "_locomotionLeftArmPoseOwnedLastFrame = locomotionOwnsLeftArm;" in locomotion
    assert "_locomotionRightArmPoseOwnedLastFrame = locomotionOwnsRightArm;" in locomotion


def test_gesture_arm_authority_matches_bones_each_action_actually_writes() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    left = source[
        source.index("private static bool GestureOwnsLeftUpperArm") :
        source.index("private static bool GestureOwnsRightUpperArm")
    ]
    right = source[
        source.index("private static bool GestureOwnsRightUpperArm") :
        source.index("private bool HasSourceDerivedNaturalPosture")
    ]

    # The current performed gesture set never writes the left upper arm.
    assert "return false;" in left
    for gesture_id in ("small_shrug", "present", "neutral"):
        assert f'gesture.id == "{gesture_id}"' not in left

    # Present and neutral write/reset the right arm. Small shrug owns only
    # shoulder translation, and unsupported ids must fail closed without
    # stealing either locomotion arm.
    assert 'gesture.id == "present"' in right
    assert 'gesture.id == "neutral"' in right
    assert 'gesture.id == "small_shrug"' not in right


def test_stop_only_blends_back_the_locomotion_arms_walk_actually_owned() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    locomotion = source[source.index("private bool ApplyLocomotion") : source.index("private bool ApplyGesture")]
    stop = locomotion[
        locomotion.index('if (locomotion.action == "stop")') :
        locomotion.index('if (locomotion.action == "turn_left"')
    ]

    assert (
        "BlendLocomotionPoseToBase(locomotionBlend, "
        "_locomotionLeftArmPoseOwnedLastFrame, _locomotionRightArmPoseOwnedLastFrame);"
        in stop
    )

    blend = source[source.index("private void BlendLocomotionPoseToBase") : source.index("private bool ApplyLocomotion")]
    assert "bool includeLeftArm" in blend
    assert "bool includeRightArm" in blend
    assert "if (includeLeftArm)" in blend
    assert "if (includeRightArm)" in blend
