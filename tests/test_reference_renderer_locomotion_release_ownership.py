from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def source() -> str:
    return DRIVER.read_text(encoding="utf-8")


def test_core_gait_ownership_is_per_channel() -> None:
    s = source()
    for name in ("HipsPosition", "LeftUpperLeg", "RightUpperLeg", "LeftLowerLeg", "RightLowerLeg"):
        assert f"_locomotion{name}OwnedLastFrame" in s
    refresh = s[s.index("private void RefreshLocomotionCoreAggregateOwnership") : s.index("private void PrepareLocomotionOwnershipForFrame")]
    for name in ("HipsPosition", "LeftUpperLeg", "RightUpperLeg", "LeftLowerLeg", "RightLowerLeg"):
        assert f"_locomotion{name}OwnedLastFrame" in refresh


def test_external_rewrite_relinquishes_channel_even_during_stop() -> None:
    s = source()
    pos = s[s.index("private void PrepareLocomotionPositionChannel") : s.index("private void PrepareLocomotionRotationChannel")]
    rot = s[s.index("private void PrepareLocomotionRotationChannel") : s.index("private void RefreshLocomotionCoreAggregateOwnership")]
    for block, release in ((pos, "releasePosition = target.localPosition;"), (rot, "releaseRotation = target.localRotation;")):
        changed = block[block.index("if (!stillBodyRig)") : block.index("if (!wantsOwnership)")]
        assert release in changed
        assert "ownedLastFrame = false;" in changed
        assert "return;" in changed


def test_stop_blends_only_channels_still_owned() -> None:
    s = source()
    blend = s[s.index("private void BlendLocomotionPoseToBase") : s.index("private bool ApplyLocomotion")]
    for guard in (
        "_locomotionHipsPositionOwnedLastFrame && _hips != null",
        "_locomotionLeftUpperLegOwnedLastFrame && _leftUpperLeg != null",
        "_locomotionRightUpperLegOwnedLastFrame && _rightUpperLeg != null",
        "_locomotionLeftLowerLegOwnedLastFrame && _leftLowerLeg != null",
        "_locomotionRightLowerLegOwnedLastFrame && _rightLowerLeg != null",
    ):
        assert guard in blend
    stop = s[s.index('if (locomotion.action == "stop")') : s.index('if (locomotion.action == "turn_left"')]
    assert "_locomotionPoseOwnedLastFrame ||" in stop
    assert "_locomotionLeftArmPoseOwnedLastFrame ||" in stop
    assert "_locomotionRightArmPoseOwnedLastFrame" in stop


def test_null_and_turn_do_not_mutate_ownership_after_prepare() -> None:
    s = source()
    apply = s[s.index("private bool ApplyLocomotion") : s.index("private bool ApplyGesture")]
    null = apply[apply.index("if (locomotion == null)") : apply.index("var locomotionBlend")]
    turn = apply[apply.index('if (locomotion.action == "turn_left"') : apply.index('if (locomotion.action != "walk")')]
    assert "OwnedLastFrame = false" not in null
    assert "OwnedLastFrame = false" not in turn


def test_stop_respects_current_gesture_arm_precedence() -> None:
    s = source()
    prepare = s[s.index("private void PrepareLocomotionOwnershipForFrame") : s.index("private void AcquireLocomotionOwnershipForFrame")]
    assert "stopKeepsLeftArm" in prepare
    assert "!GestureOwnsLeftUpperArm(_state.gesture)" in prepare
    assert "stopKeepsRightArm" in prepare
    assert "!GestureOwnsRightUpperArm(_state.gesture)" in prepare


def test_gesture_to_walk_acquires_after_gesture_release() -> None:
    s = source()
    late = s[s.index("private void LateUpdate()") : s.index("private void BindAvatarIfNeeded()")]
    assert late.index("PrepareLocomotionOwnershipForFrame();") < late.index("PrepareGestureOwnershipForFrame(") < late.index("AcquireLocomotionOwnershipForFrame();")


def test_incomplete_walk_cannot_acquire_core_channels() -> None:
    s = source()
    can = s[s.index("private bool CanRealizeWalk") : s.index("private void PrepareLocomotionPositionChannel")]
    for needle in ("_hips != null", "_leftUpperLeg != null", "_rightUpperLeg != null", "_leftLowerLeg != null", "_rightLowerLeg != null", "_avatarHeight > 0.0001f"):
        assert needle in can
    acquire = s[s.index("private void AcquireLocomotionOwnershipForFrame") : s.index("private void CommitLocomotionOwnershipForFrame")]
    assert "if (!CanRealizeWalk(locomotion))" in acquire
    assert "return;" in acquire


def test_stop_external_rewrite_model_preserves_external_pose() -> None:
    owned, release, applied, current = True, 10.0, 25.0, 42.0
    if current != applied:
        release, owned = current, False
    if owned:
        current = 0.0
    assert (owned, current, release) == (False, 42.0, 42.0)


def test_lifecycle_resets_per_channel_core_flags() -> None:
    s = source()
    bind = s[s.index("private void BindAvatarIfNeeded()") : s.index("private bool CanRealizeWalk")]
    neutral = s[s.index("public void RestoreNeutralPose()") :]
    for section in (bind, neutral):
        for name in ("HipsPosition", "LeftUpperLeg", "RightUpperLeg", "LeftLowerLeg", "RightLowerLeg"):
            assert f"_locomotion{name}OwnedLastFrame = false;" in section
