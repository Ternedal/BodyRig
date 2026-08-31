from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "bodyrig" / "bridges" / "opencv_fidelity_evaluator.py"


def test_evaluator_revision_four_measures_reference_relative_facial_definition() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert 'REVISION = "4"' in source
    assert "def facial_definition_statistics" in source
    assert "def facial_definition_similarity" in source
    assert '"eye_edge_density"' in source
    assert '"midface_edge_density"' in source
    assert "strongest = sorted(" in source


def test_low_definition_caps_both_photorealism_and_human_plausibility() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "definition_photorealism_cap = clamp(0.45 + 0.55 * facial_definition_score)" in source
    assert "photorealism_score = min(raw_photorealism_score, definition_photorealism_cap)" in source
    assert "facial_definition=facial_definition_score" in source
    assert '"facial_definition": round(facial_definition_score, 6)' in source


def test_definition_diagnostics_remain_non_biometric_and_human_review_stays_authoritative() -> None:
    source = SOURCE.read_text(encoding="utf-8")
    assert "reference-relative-local-feature-definition-not-biometric-identification" in source
    assert '"human_visual_authority_required": True' in source
    assert 'SEMANTICS = "visual-fidelity-not-identity-verification"' in source
