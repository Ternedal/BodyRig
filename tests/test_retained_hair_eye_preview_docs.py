from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "retained-hair-eye-preview.md"


def test_retained_preview_doc_keeps_comparison_only_boundary_explicit() -> None:
    text = DOC.read_text(encoding="utf-8")

    assert "reconstruction_rerun=false" in text
    assert "comparison_only=true" in text
    assert "full_fidelity_component_complete=false" in text
    assert "human_review_required=true" in text
    assert "production_activation=false" in text
    assert "Iris appearance remains review-pending" in text
    assert "eyelashes remain missing" in text
    assert "not full-fidelity acceptance" in text
