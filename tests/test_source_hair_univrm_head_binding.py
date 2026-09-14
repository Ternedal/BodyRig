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


def test_humanoid_head_must_functionally_drive_canonical_skin_head_and_hair() -> None:
    source = HAIR_PROBE.read_text(encoding="utf-8")

    resolve = source.index("ResolveRendererHeadBone(bones)")
    baseline_skin = source.index("baselineRendererHeadWorldRotation = rendererHead.rotation")
    neutral = source.index("neutral = BakeVertices(hair)")
    turn = source.index("head.localRotation = baselineRotation * Quaternion.Euler(0f, HeadTurnDegrees, 0f)")
    humanoid_gate = source.index("Humanoid Head turn was not applied strongly enough")
    skin_measure = source.index("observedRendererHeadTurn = Quaternion.Angle")
    skin_gate = source.index("Canonical SMPL-X Head skin joint did not follow Humanoid Head control")
    turned = source.index("turned = BakeVertices(hair)")
    motion_gate = source.index("if (!motionObserved)")
    restore_gate = source.index("if (!restoredNeutral)")
    report_bound = source.index("head_bone_bound = true")

    assert resolve < baseline_skin < neutral < turn < humanoid_gate < skin_measure < skin_gate < turned < motion_gate < restore_gate < report_bound
    assert "HeadTurnDegrees * 0.65f" in source
    assert "Source hair did not deform with Head turn" in source
    assert "Source hair did not restore after Head turn" in source
    assert "human_review_required = true" in source
    assert "comparison_only = true" in source
    assert "hair_component_authority = false" in source
    assert "production_activation = false" in source
