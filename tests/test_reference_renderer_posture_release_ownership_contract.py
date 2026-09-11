from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_posture_release_stops_lateupdate_writes_instead_of_restoring_bind_pose() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late_update = source[
        source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")
    ]

    # Animator/VRMA has already evaluated before LateUpdate. Once performed
    # posture authority is absent, BodyRig must stop writing instead of
    # restoring a captured bind pose over the external animation frame.
    assert "_postureOwnedPoseLastFrame" not in source
    assert "_sourcePostureOffsetsOwnedLastFrame" not in source
    assert "var performedPosture" not in late_update
    assert "if (sourceNaturalPosture)" in late_update
    assert "RestorePostureOffsetsForFrame();" in late_update
    assert "_spine.localRotation = _spineBaseRotation;" not in late_update


def test_explicit_restore_neutral_pose_remains_the_deliberate_bind_pose_reset() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    neutral = source[source.index("public void RestoreNeutralPose()") :]

    assert "RestorePostureOffsetsForFrame();" in neutral
    assert "if (_spine != null) _spine.localRotation = _spineBaseRotation;" in neutral
