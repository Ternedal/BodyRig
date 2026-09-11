from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_posture_release_restores_only_transforms_still_owned_by_bodyrig() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]
    prepare = source[
        source.index("private void PreparePostureOwnershipForFrame") :
        source.index("private void CommitPostureOwnershipForFrame")
    ]
    commit = source[
        source.index("private void CommitPostureOwnershipForFrame") : source.index("private void LateUpdate()")
    ]

    assert "var performedPosture = HasSupportedPerformedPosture();" in late_update
    assert "PreparePostureOwnershipForFrame(performedPosture, sourceNaturalPosture);" in late_update
    assert late_update.index("PreparePostureOwnershipForFrame") < late_update.index("RestorePostureOffsetsForFrame();")
    assert "CommitPostureOwnershipForFrame(sourceNaturalPosture, PostureRealized);" in late_update
    assert late_update.index("PostureRealized = ApplyPosture();") < late_update.index("CommitPostureOwnershipForFrame")

    assert "SameRotation(_spine.localRotation, _postureAppliedSpineRotation)" in prepare
    assert "if (!stillBodyRigSpine)" in prepare
    assert "_postureReleaseSpineRotation = _spine.localRotation;" in prepare
    assert "if (!performedPosture)" in prepare
    assert "if (stillBodyRigSpine)" in prepare
    assert "_spine.localRotation = _postureReleaseSpineRotation;" in prepare

    for current, applied, release in (
        ("_head.localPosition", "_postureAppliedHeadPosition", "_postureReleaseHeadPosition"),
        ("_hips.localRotation", "_postureAppliedHipsRotation", "_postureReleaseHipsRotation"),
        ("_leftShoulder.localPosition", "_postureAppliedLeftShoulderPosition", "_postureReleaseLeftShoulderPosition"),
        ("_rightShoulder.localPosition", "_postureAppliedRightShoulderPosition", "_postureReleaseRightShoulderPosition"),
    ):
        assert current in prepare
        assert applied in prepare
        assert release in prepare

    assert "if (!sourceNaturalPosture)" in prepare
    assert "_sourcePostureOffsetsOwnedLastFrame = false;" in prepare
    assert "_postureSpineOwnedLastFrame = postureRealized && _spine != null;" in commit
    assert "_sourcePostureOffsetsOwnedLastFrame = sourceNaturalPosture && postureRealized;" in commit


def test_posture_release_detects_external_animator_rewrites_per_channel() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    prepare = source[
        source.index("private void PreparePostureOwnershipForFrame") :
        source.index("private void CommitPostureOwnershipForFrame")
    ]

    assert "private static bool SamePosition" in source
    assert "private static bool SameRotation" in source
    assert "if (_head != null && !headStillBodyRig) _postureReleaseHeadPosition = _head.localPosition;" in prepare
    assert "if (_hips != null && !hipsStillBodyRig) _postureReleaseHipsRotation = _hips.localRotation;" in prepare
    assert "if (_leftShoulder != null && !leftShoulderStillBodyRig) _postureReleaseLeftShoulderPosition = _leftShoulder.localPosition;" in prepare
    assert "if (_rightShoulder != null && !rightShoulderStillBodyRig) _postureReleaseRightShoulderPosition = _rightShoulder.localPosition;" in prepare

    assert "if (_head != null && headStillBodyRig) _head.localPosition = _postureReleaseHeadPosition;" in prepare
    assert "if (_hips != null && hipsStillBodyRig) _hips.localRotation = _postureReleaseHipsRotation;" in prepare
    assert "if (_leftShoulder != null && leftShoulderStillBodyRig) _leftShoulder.localPosition = _postureReleaseLeftShoulderPosition;" in prepare
    assert "if (_rightShoulder != null && rightShoulderStillBodyRig) _rightShoulder.localPosition = _postureReleaseRightShoulderPosition;" in prepare


def test_explicit_restore_neutral_pose_remains_the_deliberate_bind_pose_reset() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    neutral = source[source.index("public void RestoreNeutralPose()") :]

    assert "RestorePostureOffsetsForFrame();" in neutral
    assert "if (_spine != null) _spine.localRotation = _spineBaseRotation;" in neutral
    assert "_postureSpineOwnedLastFrame = false;" in neutral
    assert "_sourcePostureOffsetsOwnedLastFrame = false;" in neutral
