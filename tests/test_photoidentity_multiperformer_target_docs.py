from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_target_isolation_docs_require_human_contamination_review_before_authority() -> None:
    text = (ROOT / "docs" / "MULTIPERFORMER_TRACK_REVIEW.md").read_text(encoding="utf-8").lower()
    assert "target_isolation_human_review_required=true" in text
    assert "target_isolated_source_authority=false" in text
    assert "record-photoidentity-multiperformer-target-isolation.ps1" in text
    assert "authority_scope=accepted-samples-only" in text
    assert "original multi-performer video must never be routed directly" in text
