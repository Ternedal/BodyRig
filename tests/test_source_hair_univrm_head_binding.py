from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HAIR_PROBE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigHairDeformationProbe.cs"


def test_hair_probe_accepts_only_canonical_smplx_normalized_equivalence() -> None:
    source = HAIR_PROBE.read_text(encoding="utf-8")

    for marker in (
        "ResolveRendererHeadBone(bones, animator, head)",
        "bone == humanoidHead",
        "CanonicalSmplxNeckJointIndex = 12",
        "CanonicalSmplxHeadJointIndex = 15",
        "var canonicalNeck = bones[CanonicalSmplxNeckJointIndex]",
        "var canonicalHead = bones[CanonicalSmplxHeadJointIndex]",
        "Vector3.Distance(canonicalHead.position, humanoidHead.position)",
        "Vector3.Distance(canonicalNeck.position, humanoidNeck.position)",
        "Canonical SMPL-X Head is not position-equivalent to Humanoid Head",
        "Canonical SMPL-X Neck is not position-equivalent to Humanoid Neck",
    ):
        assert marker in source

    assert "MaximumEquivalentHeadOffsetMeters = 0.05f" in source
    assert "MaximumEquivalentNeckOffsetMeters = 0.05f" in source
    assert "HasNamedAncestor" not in source
    assert "string.Equals(bone.name, humanoidHead.name" not in source


def test_canonical_head_equivalence_does_not_replace_real_motion_proof() -> None:
    source = HAIR_PROBE.read_text(encoding="utf-8")

    resolve = source.index("ResolveRendererHeadBone(bones, animator, head)")
    neutral = source.index("neutral = BakeVertices(hair)")
    turn = source.index("head.localRotation = baselineRotation * Quaternion.Euler(0f, HeadTurnDegrees, 0f)")
    turned = source.index("turned = BakeVertices(hair)")
    motion_gate = source.index("if (!motionObserved)")
    restore_gate = source.index("if (!restoredNeutral)")
    report_bound = source.index("head_bone_bound = true")

    assert resolve < neutral < turn < turned < motion_gate < restore_gate < report_bound
    assert "Source hair did not deform with Head turn" in source
    assert "Source hair did not restore after Head turn" in source
    assert "human_review_required = true" in source
    assert "comparison_only = true" in source
    assert "hair_component_authority = false" in source
    assert "production_activation = false" in source
