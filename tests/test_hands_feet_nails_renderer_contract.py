from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigFidelitySnapshotCapture.cs"


def test_hand_foot_detail_render_manifest_is_separate_from_v1_fidelity_manifest() -> None:
    text = SOURCE.read_text(encoding="utf-8")

    assert 'private const string Format = "bodyrig-fidelity-render-set";' in text
    assert 'private const string HandsFeetNailsFormat = "bodyrig-hands-feet-nails-render-set";' in text
    assert 'private const string HandsFeetNailsSemantics = "human-review-diagnostic-not-physical-pass";' in text
    assert '"hands-feet-nails-render-set.json"' in text
    assert "snapshots = entries.ToArray()" in text
    assert "snapshots = detailEntries.ToArray()" in text
    assert text.index('"fidelity-render-set.json"') < text.index('"hands-feet-nails-render-set.json"')


def test_hand_foot_detail_views_are_exact_and_humanoid_bone_bound() -> None:
    text = SOURCE.read_text(encoding="utf-8")

    for bone in (
        "HumanBodyBones.LeftHand",
        "HumanBodyBones.RightHand",
        "HumanBodyBones.LeftFoot",
        "HumanBodyBones.RightFoot",
    ):
        assert bone in text

    positions = [text.index(f'"{name}"') for name in ("left_hand", "right_hand", "left_foot", "right_foot")]
    assert positions == sorted(positions)
    assert "detailEntries.Count == 4" in text


def test_old_machine_evaluator_view_sequence_remains_unchanged() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    expected = (
        'new CameraPose("front-full"',
        'new CameraPose("three-quarter-full"',
        'new CameraPose("side-full"',
        'new CameraPose("face-front"',
    )
    positions = [text.index(value) for value in expected]
    assert positions == sorted(positions)
    canonical_block_start = text.index("var canonicalPoses = new[]")
    canonical_block_end = text.index("// Human-review diagnostics", canonical_block_start)
    block = text[canonical_block_start:canonical_block_end]
    assert block.count("new CameraPose(") == 4
    assert "left_hand" not in block
    assert "left_foot" not in block
