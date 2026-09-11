from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_gesture_transition_releases_only_channels_still_owned_by_bodyrig() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    prepare = source[
        source.index("private void PrepareGestureOwnershipForFrame") :
        source.index("private void CommitGestureOwnershipForFrame")
    ]

    assert "SamePosition(_leftShoulder.localPosition, _gestureAppliedLeftShoulderPosition)" in prepare
    assert "SamePosition(_rightShoulder.localPosition, _gestureAppliedRightShoulderPosition)" in prepare
    assert "SameRotation(_rightUpperArm.localRotation, _gestureAppliedRightUpperArmRotation)" in prepare
    assert "SameRotation(_rightLowerArm.localRotation, _gestureAppliedRightLowerArmRotation)" in prepare

    assert "if (!ownsLeftShoulder)" in prepare
    assert "_leftShoulder.localPosition = _gestureReleaseLeftShoulderPosition;" in prepare
    assert "if (!ownsRightShoulder)" in prepare
    assert "_rightShoulder.localPosition = _gestureReleaseRightShoulderPosition;" in prepare
    assert "if (!ownsRightUpperArm)" in prepare
    assert "_rightUpperArm.localRotation = _gestureReleaseRightUpperArmRotation;" in prepare
    assert "if (!ownsRightLowerArm)" in prepare
    assert "_rightLowerArm.localRotation = _gestureReleaseRightLowerArmRotation;" in prepare

    assert "if (!stillBodyRig)" in prepare
    assert "_gestureReleaseLeftShoulderPosition = _leftShoulder.localPosition;" in prepare
    assert "_gestureReleaseRightShoulderPosition = _rightShoulder.localPosition;" in prepare
    assert "_gestureReleaseRightUpperArmRotation = _rightUpperArm.localRotation;" in prepare
    assert "_gestureReleaseRightLowerArmRotation = _rightLowerArm.localRotation;" in prepare


def test_gesture_transition_ownership_matches_actual_action_writes() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") :
        source.index("private void BindAvatarIfNeeded()")
    ]

    assert 'gestureId == "small_shrug" && _leftShoulder != null && _rightShoulder != null' in late_update
    assert 'smallShrugOwnsShoulders || (gestureId == "neutral" && _leftShoulder != null)' in late_update
    assert 'smallShrugOwnsShoulders || (gestureId == "neutral" && _rightShoulder != null)' in late_update
    assert 'gestureId == "present" && _rightUpperArm != null && _rightLowerArm != null' in late_update
    assert 'presentOwnsRightArm || (gestureId == "neutral" && _rightUpperArm != null)' in late_update
    assert 'presentOwnsRightArm || (gestureId == "neutral" && _rightLowerArm != null)' in late_update

    prepare = late_update.index("PrepareGestureOwnershipForFrame(")
    locomotion = late_update.index("LocomotionRealized = ApplyLocomotion(dt);")
    gesture = late_update.index("GestureRealized = ApplyGesture();")
    posture = late_update.index("PostureRealized = ApplyPosture();")
    commit = late_update.index("CommitGestureOwnershipForFrame(")
    assert prepare < locomotion < gesture < posture < commit


def test_gesture_ownership_commit_tracks_final_composed_channels() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    commit = source[
        source.index("private void CommitGestureOwnershipForFrame") :
        source.index("private void PreparePostureOwnershipForFrame")
    ]

    for line in (
        "_gestureAppliedLeftShoulderPosition = _leftShoulder.localPosition;",
        "_gestureAppliedRightShoulderPosition = _rightShoulder.localPosition;",
        "_gestureAppliedRightUpperArmRotation = _rightUpperArm.localRotation;",
        "_gestureAppliedRightLowerArmRotation = _rightLowerArm.localRotation;",
    ):
        assert line in commit


def test_gesture_ownership_bookkeeping_resets_on_rebind_and_explicit_neutral_restore() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    bind = source[
        source.index("private void BindAvatarIfNeeded()") :
        source.index("private float LocomotionBlend")
    ]
    neutral = source[source.index("public void RestoreNeutralPose()") :]

    for flag in (
        "_gestureLeftShoulderOwnedLastFrame",
        "_gestureRightShoulderOwnedLastFrame",
        "_gestureRightUpperArmOwnedLastFrame",
        "_gestureRightLowerArmOwnedLastFrame",
        "_shoulderOwnershipOrderKnown",
        "_gestureShoulderLayerPrecedesPosture",
    ):
        assert f"{flag} = false;" in bind
        assert f"{flag} = false;" in neutral


def test_overlapping_shoulder_release_preserves_layer_acquisition_order() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") :
        source.index("private void BindAvatarIfNeeded()")
    ]

    assert "var gestureShouldersOwnedLastFrame =" in late_update
    assert "_gestureLeftShoulderOwnedLastFrame || _gestureRightShoulderOwnedLastFrame" in late_update
    assert "var postureShouldersOwnedLastFrame = _sourcePostureOffsetsOwnedLastFrame;" in late_update
    assert "var gestureOwnsShoulders = gestureOwnsLeftShoulder || gestureOwnsRightShoulder;" in late_update
    assert "var postureOwnsShoulders = sourceNaturalPosture &&" in late_update
    assert "if (gestureOwnsShoulders && postureOwnsShoulders && !_shoulderOwnershipOrderKnown)" in late_update
    assert "gestureShouldersOwnedLastFrame && !postureShouldersOwnedLastFrame" in late_update
    assert "postureShouldersOwnedLastFrame && !gestureShouldersOwnedLastFrame" in late_update
    assert "_gestureShoulderLayerPrecedesPosture = true;" in late_update
    assert "_gestureShoulderLayerPrecedesPosture = false;" in late_update
    assert "_shoulderOwnershipOrderKnown = true;" in late_update
    assert "if (_shoulderOwnershipOrderKnown && !_gestureShoulderLayerPrecedesPosture)" in late_update
    assert "PreparePostureOwnershipForFrame(performedPosture, sourceNaturalPosture);" in late_update
    assert "PrepareGestureOwnershipForFrame(" in late_update
    assert "if (!(gestureShouldersOwnedAfterCommit && postureShouldersOwnedAfterCommit))" in late_update
    assert "_shoulderOwnershipOrderKnown = false;" in late_update

    # Gesture-first acquisition: release shrug before posture observes the shared
    # shoulder, so posture refreshes its release baseline to the de-shrugged pose.
    external = 0.0
    shrugged = 0.02
    gesture_release = external
    posture_release = shrugged
    composed_last_frame = shrugged
    current = shrugged
    current = gesture_release
    if current != composed_last_frame:
        posture_release = current
    assert posture_release == external

    # Posture-first acquisition: posture must inspect its still-composed value
    # before gesture release restores the posture-applied baseline. Otherwise
    # posture would mistake the gesture release for an external rewrite and keep
    # the posture offset forever.
    external = 0.0
    postured = 0.01
    posture_release = external
    posture_applied_last_frame = postured
    gesture_release = postured
    current = postured
    posture_still_bodyrig = current == posture_applied_last_frame
    if not posture_still_bodyrig:
        posture_release = current
    current = gesture_release
    assert current == postured
    current = posture_release
    assert current == external
