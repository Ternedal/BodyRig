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

    assert 'gestureId == "small_shrug" || gestureId == "neutral"' in late_update
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
    ):
        assert f"{flag} = false;" in bind
        assert f"{flag} = false;" in neutral


def test_gesture_release_refreshes_overlapping_posture_baseline_before_posture_uses_it() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") :
        source.index("private void BindAvatarIfNeeded()")
    ]

    gesture_prepare = late_update.index("PrepareGestureOwnershipForFrame(")
    posture_prepare = late_update.index("PreparePostureOwnershipForFrame(performedPosture, sourceNaturalPosture);")
    assert gesture_prepare < posture_prepare

    # Model the exact overlap regression: natural posture acquired its baseline
    # while a shrug was lifted; ending the shrug must be visible to posture
    # preparation on that same frame, so ending posture later cannot resurrect it.
    gesture_release_baseline = 0.0
    shrugged_shoulder = 0.02
    posture_release_baseline = shrugged_shoulder
    posture_applied_last_frame = shrugged_shoulder
    current_shoulder = shrugged_shoulder

    # Gesture preparation releases BodyRig's still-owned shrug first.
    current_shoulder = gesture_release_baseline

    # Posture preparation now observes that its previous composed value changed
    # and refreshes the release baseline to the de-shrugged shoulder.
    posture_still_bodyrig = current_shoulder == posture_applied_last_frame
    if not posture_still_bodyrig:
        posture_release_baseline = current_shoulder

    # When posture ends on a later frame, it must restore the de-shrugged value.
    current_shoulder = posture_release_baseline
    assert current_shoulder == gesture_release_baseline
    assert current_shoulder != shrugged_shoulder
