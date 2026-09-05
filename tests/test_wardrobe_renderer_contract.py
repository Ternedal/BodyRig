from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigFidelitySnapshotCapture.cs"


def test_historical_fidelity_views_remain_unchanged() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    expected = (
        'new CameraPose("front-full"',
        'new CameraPose("three-quarter-full"',
        'new CameraPose("side-full"',
        'new CameraPose("face-front"',
    )
    for marker in expected:
        assert marker in text
    assert 'Path.Combine(root, "fidelity-render-set.json")' in text
    assert 'public string semantics = "visual-fidelity-not-identity-verification";' in text


def test_wardrobe_views_use_canonical_source_comparison_ids() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert 'private const string WardrobeFormat = "bodyrig-wardrobe-render-set";' in text
    assert 'private const string WardrobeSemantics = "human-review-diagnostic-not-physical-pass";' in text
    markers = (
        'new CameraPose("front"',
        'new CameraPose("left_side"',
        'new CameraPose("right_side"',
        'new CameraPose("back"',
    )
    positions = [text.index(marker) for marker in markers]
    assert positions == sorted(positions)
    assert 'Path.Combine(root, "wardrobe-render-set.json")' in text
    assert "wardrobe_front" not in text
    assert "wardrobe_left" not in text
    assert "wardrobe_right" not in text
    assert "wardrobe_back" not in text


def test_wardrobe_manifest_is_diagnostic_not_machine_authority() -> None:
    text = SOURCE.read_text(encoding="utf-8")
    assert "WardrobeManifest" in text
    assert "wardrobeEntries.Count == 4" in text
    assert 'private const string WardrobeSemantics = "human-review-diagnostic-not-physical-pass";' in text
    assert 'Path.Combine(root, "wardrobe-render-set.json")' in text
    assert 'Path.Combine(root, "fidelity-render-set.json")' in text
