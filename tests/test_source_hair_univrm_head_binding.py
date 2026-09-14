from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HAIR_PROBE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigHairDeformationProbe.cs"


def test_hair_probe_accepts_only_proven_normalized_univrm_head_equivalence() -> None:
    source = HAIR_PROBE.read_text(encoding="utf-8")

    for marker in (
        "ResolveRendererHeadBone(bones, animator, head)",
        "bone == humanoidHead",
        "HumanBodyBones.Neck",
        "string.Equals(bone.name, humanoidHead.name, StringComparison.Ordinal)",
        "Vector3.Distance(bone.position, humanoidHead.position) > MaximumEquivalentHeadOffsetMeters",
        "HasNamedAncestor(bone.parent, humanoidNeck.name, MaximumEquivalentNeckAncestorDepth)",
        "Source hair review renderer has ambiguous normalized Head skin bindings",
        "Source hair review renderer is not bound to the canonical Humanoid Head hierarchy",
    ):
        assert marker in source

    assert "MaximumEquivalentHeadOffsetMeters = 0.05f" in source
    assert "MaximumEquivalentNeckAncestorDepth = 3" in source


def test_normalized_head_equivalence_does_not_replace_real_motion_proof() -> None:
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
