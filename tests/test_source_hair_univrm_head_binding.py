from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HAIR_PROBE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigHairDeformationProbe.cs"


def test_hair_probe_uses_canonical_smplx_skin_joint_identity() -> None:
    source = HAIR_PROBE.read_text(encoding="utf-8")

    for marker in (
        "ResolveRendererHeadBone(bones)",
        "CanonicalSmplxNeckJointIndex = 12",
        "CanonicalSmplxHeadJointIndex = 15",
        'CanonicalSmplxNeckName = "smplx_neck"',
        'CanonicalSmplxHeadName = "smplx_head"',
        "var canonicalNeck = bones[CanonicalSmplxNeckJointIndex]",
        "var canonicalHead = bones[CanonicalSmplxHeadJointIndex]",
        "string.Equals(canonicalNeck.name, CanonicalSmplxNeckName, StringComparison.Ordinal)",
        "string.Equals(canonicalHead.name, CanonicalSmplxHeadName, StringComparison.Ordinal)",
    ):
        assert marker in source

    assert "MaximumEquivalentHeadOffsetMeters" not in source
    assert "MaximumEquivalentNeckOffsetMeters" not in source
    assert "position-equivalent" not in source
    assert "HasNamedAncestor" not in source


def test_humanoid_head_is_driven_through_human_pose_and_skin_head_rotation_is_diagnostic_only() -> None:
    source = HAIR_PROBE.read_text(encoding="utf-8")

    for marker in (
        "new HumanPoseHandler(animator.avatar, animator.transform)",
        "poseHandler.GetHumanPose(ref baselinePose)",
        "HumanTrait.MuscleFromBone(headBoneIndex, HeadYawDofIndex)",
        "HumanTrait.GetMuscleDefaultMax(muscleIndex)",
        "HumanTrait.GetMuscleDefaultMin(muscleIndex)",
        "poseHandler.SetHumanPose(ref turnedPose)",
        "observedHeadTurn = Quaternion.Angle(baselineRendererHeadWorldRotation, rendererHead.rotation)",
        "canonical skin-head transform diagnostic",
        "poseHandler.SetHumanPose(ref restorePose)",
    ):
        assert marker in source

    assert "head.localRotation =" not in source
    assert "HeadYawDofIndex = 1" in source
    assert "Canonical SMPL-X Head skin joint did not follow Unity Humanoid Head yaw strongly enough" not in source
    assert "HeadTurnDegrees * 0.65f" not in source


def test_functional_hair_motion_and_restoration_are_the_authoritative_machine_gates() -> None:
    source = HAIR_PROBE.read_text(encoding="utf-8")

    resolve = source.index("ResolveRendererHeadBone(bones)")
    neutral = source.index("neutral = BakeVertices(hair)")
    human_pose = source.index("poseHandler.SetHumanPose(ref turnedPose)")
    skin_measure = source.index("observedHeadTurn = Quaternion.Angle")
    turned = source.index("turned = BakeVertices(hair)")
    restore_pose = source.index("poseHandler.SetHumanPose(ref restorePose)")
    restored = source.index("restored = BakeVertices(hair)")
    motion_gate = source.index("if (!motionObserved)")
    restore_gate = source.index("if (!restoredNeutral)")
    report_bound = source.index("head_bone_bound = true")

    assert resolve < neutral < human_pose < skin_measure < turned < restore_pose < restored < motion_gate < restore_gate < report_bound
    assert "Source hair did not deform with Humanoid Head pose" in source
    assert "Source hair did not restore after Head turn" in source
    assert "MinimumMotionRmsMeters = 0.00025f" in source
    assert "MinimumMotionMaxMeters = 0.001f" in source
    assert "MaximumRestorationRmsMeters = 0.00025f" in source
    assert "MaximumRestorationMaxMeters = 0.001f" in source
    assert "human_review_required = true" in source
    assert "comparison_only = true" in source
    assert "hair_component_authority = false" in source
    assert "production_activation = false" in source
