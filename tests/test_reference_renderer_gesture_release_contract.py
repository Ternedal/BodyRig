from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_gesture_transition_release_is_anatomically_scoped_and_non_destructive() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    prepare = source[
        source.index("private void PrepareGestureOwnershipForFrame") :
        source.index("private void CommitGestureOwnershipForFrame")
    ]

    assert "_gestureShoulderPoseOwnedLastFrame" in prepare
    assert "_gestureRightArmPoseOwnedLastFrame" in prepare
    assert "SamePosition(_leftShoulder.localPosition, _gestureAppliedLeftShoulderPosition)" in prepare
    assert "SamePosition(_rightShoulder.localPosition, _gestureAppliedRightShoulderPosition)" in prepare
    assert "SameRotation(_rightUpperArm.localRotation, _gestureAppliedRightUpperArmRotation)" in prepare
    assert "SameRotation(_rightLowerArm.localRotation, _gestureAppliedRightLowerArmRotation)" in prepare

    # External Animator/VRMA rewrites become the new release baseline instead
    # of being overwritten by a stale bind-pose restore.
    assert "if (!leftStillBodyRig) _gestureReleaseLeftShoulderPosition = _leftShoulder.localPosition;" in prepare
    assert "if (!rightStillBodyRig) _gestureReleaseRightShoulderPosition = _rightShoulder.localPosition;" in prepare
    assert "if (!upperStillBodyRig) _gestureReleaseRightUpperArmRotation = _rightUpperArm.localRotation;" in prepare
    assert "if (!lowerStillBodyRig) _gestureReleaseRightLowerArmRotation = _rightLowerArm.localRotation;" in prepare

    assert "if (!ownsShoulders)" in prepare
    assert "if (!ownsRightArm)" in prepare
    assert "if (_leftShoulder != null && leftStillBodyRig)" in prepare
    assert "if (_rightShoulder != null && rightStillBodyRig)" in prepare
    assert "if (_rightUpperArm != null && upperStillBodyRig)" in prepare
    assert "if (_rightLowerArm != null && lowerStillBodyRig)" in prepare


def test_gesture_transition_release_runs_before_locomotion_and_commits_final_frame_pose() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]

    assert "PrepareGestureOwnershipForFrame();" in late_update
    assert late_update.index("PrepareGestureOwnershipForFrame();") < late_update.index("LocomotionRealized = ApplyLocomotion(dt);")
    assert "CommitGestureOwnershipForFrame(GestureRealized);" in late_update
    assert late_update.index("PostureRealized = ApplyPosture();") < late_update.index("CommitGestureOwnershipForFrame(GestureRealized);")


def test_gesture_ownership_matches_actual_bones_touched_by_each_action() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    shoulder = source[
        source.index("private static bool GestureOwnsShoulderPositions") :
        source.index("private static bool GestureOwnsRightArmPose")
    ]
    right_arm = source[
        source.index("private static bool GestureOwnsRightArmPose") :
        source.index("private static bool GestureOwnsLeftUpperArm")
    ]

    assert 'gesture.id == "small_shrug" || gesture.id == "neutral"' in shoulder
    assert 'gesture.id == "present" || gesture.id == "neutral"' in right_arm


def test_gesture_release_bookkeeping_is_cleared_at_avatar_and_session_boundaries() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    bind = source[
        source.index("private void BindAvatarIfNeeded()") : source.index("private float LocomotionBlend")
    ]
    neutral = source[source.index("public void RestoreNeutralPose()") :]

    for section in (bind, neutral):
        assert "_gestureShoulderPoseOwnedLastFrame = false;" in section
        assert "_gestureRightArmPoseOwnedLastFrame = false;" in section
