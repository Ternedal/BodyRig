from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_target_crop_quality_docs_preserve_pre_sufficiency_boundary() -> None:
    text = (ROOT / "docs" / "MULTIPERFORMER_TRACK_REVIEW.md").read_text(encoding="utf-8").lower()
    assert "record-photoidentity-target-crop-detail-quality.ps1" in text
    assert "detail_quality_threshold" in text
    assert "source_detail_quality_authority=true" in text
    assert "photoidentity_source_evidence_authority=false" in text
    assert "reconstruction_permitted=false" in text
    assert "production_activation=false" in text
    assert "aggregate-photoidentity-multiperformer-detail-evidence.ps1" in text
    assert "every `-qualityreceipt` must be paired positionally with its exact human-reviewed `-candidateroot`" in text
    assert "photoidentity-human-source-chain-v2" in text
    assert "body-job registry authority v3" in text
    assert "removal, replacement or tampering therefore fails closed" in text
    assert "intermediate multi-performer aggregation is also not production authority by itself" in text
