from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_multiperformer_docs_route_human_attestation_to_target_isolation() -> None:
    text = (ROOT / "docs" / "MULTIPERFORMER_TRACK_REVIEW.md").read_text(encoding="utf-8").lower()
    assert "record-photoidentity-multiperformer-track-attestation.ps1" in text
    assert "target_isolated_source_authority=false" in text
    assert "photoidentity_source_evidence_authority=false" in text
    assert "reconstruction_permitted=false" in text
    assert "production_activation=false" in text
    assert "must never be routed directly into the single-person analyzer" in text
