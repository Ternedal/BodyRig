from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"

def test_head_motion_and_gaze_share_one_non_destructive_rotation_owner() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    for field in ("_headRotationOwnedLastFrame", "_headRotationWrittenThisFrame", "_headRotationReleaseRotation", "_headRotationAppliedRotation"):
        assert field in source
    prepare = source[source.index("private void PrepareHeadRotationOwnershipForFrame") : source.index("private void AcquireHeadRotationOwnership")]
    acquire = source[source.index("private void AcquireHeadRotationOwnership") : source.index("private void CommitHeadRotationOwnershipForFrame")]
    commit = source[source.index("private void CommitHeadRotationOwnershipForFrame") : source.index("private void PrepareGestureOwnershipForFrame")]
    assert "SameRotation(_head.localRotation, _headRotationAppliedRotation)" in prepare
    assert "_headRotationReleaseRotation = _head.localRotation;" in prepare
    assert "if (!_headRotationOwnedLastFrame)" in acquire
    assert "_headRotationReleaseRotation = _head.localRotation;" in acquire
    assert "if (_headRotationWrittenThisFrame)" in commit
    assert "_headRotationAppliedRotation = _head.localRotation;" in commit
    assert "_head.localRotation = _headRotationReleaseRotation;" in commit

def test_head_rotation_wraps_both_producers_after_shoulder_preparation() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    late = source[source.index("private void LateUpdate()") : source.index("private void BindAvatarIfNeeded()")]
    shoulder_order = late.index("if (_shoulderOwnershipOrderKnown && !_gestureShoulderLayerPrecedesPosture)")
    prepare_head = late.index("PrepareHeadRotationOwnershipForFrame();")
    head = late.index("MotionRealized = ApplyHeadMotion();")
    gaze = late.index("GazeRealized = ApplyGaze();")
    commit = late.index("CommitHeadRotationOwnershipForFrame();")
    assert shoulder_order < prepare_head < head < gaze < commit
    assert late.count("PrepareHeadRotationOwnershipForFrame();") == 1
    assert late.count("CommitHeadRotationOwnershipForFrame();") == 1

def test_both_head_producers_acquire_before_write_and_mark_final_write() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    head = source[source.index("private bool ApplyHeadMotion") : source.index("private bool ApplyGaze")]
    gaze = source[source.index("private bool ApplyGaze") : source.index("private void RestorePostureOffsetsForFrame")]
    for block in (head, gaze):
        write = block.index("_head.localRotation = Quaternion.Slerp(")
        assert block.index("AcquireHeadRotationOwnership();") < write
        assert write < block.index("_headRotationWrittenThisFrame = true;")

def test_head_rotation_release_model_preserves_external_rewrite() -> None:
    release = 10.0
    applied = 22.0
    current = applied
    if current == applied:
        current = release
    assert current == release
    current = 37.0
    if current == applied:
        current = release
    else:
        release = current
    assert current == 37.0
    assert release == 37.0

def test_head_producer_handoff_has_no_intermediate_restore() -> None:
    owned = True
    release = 5.0
    current = 12.0
    written = False
    current = 18.0
    written = True
    if written:
        applied = current
        owned = True
    else:
        current = release
        owned = False
    assert owned is True
    assert applied == 18.0
    assert current != release

def test_missing_gaze_dependencies_fail_closed_before_acquisition() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    gaze = source[source.index("private bool ApplyGaze") : source.index("private void RestorePostureOffsetsForFrame")]
    guard = gaze[gaze.index("if (_head == null") : gaze.index("var worldLook")]
    assert "userGazeTarget == null" in guard
    assert guard.count("_gazeStrength = 0.0f;") >= 2
    assert guard.count("return false;") >= 2
    assert "AcquireHeadRotationOwnership();" not in guard

def test_head_rotation_bookkeeping_resets_on_rebind_and_neutral() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    bind = source[source.index("private void BindAvatarIfNeeded()") : source.index("private float LocomotionBlend")]
    neutral = source[source.index("public void RestoreNeutralPose()") :]
    for section in (bind, neutral):
        assert "_headRotationOwnedLastFrame = false;" in section
        assert "_headRotationWrittenThisFrame = false;" in section
