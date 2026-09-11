from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "record-photoidentity-target-crop-detail-quality.ps1"


def test_target_crop_quality_operator_requires_exact_human_source_review_boundary() -> None:
    text = SCRIPT.read_text(encoding="utf-8").lower()
    assert "confirmquality" in text
    assert "git -c $reporoot rev-parse head" in text
    assert "git -c $reporoot status --porcelain" in text
    assert "bodyrig.photoidentity_target_crop_quality_attestation" in text
    assert "bodyrig\\__init__.py" in text
    assert "human_source_detail_quality_attested -ne $true" in text
    assert "source_detail_quality_authority -ne $true" in text
    assert "photoidentity_source_evidence_authority -ne $false" in text
    assert "reconstruction_permitted -ne $false" in text
    assert "production_activation -ne $false" in text
    assert "remove-item -literalpath $receiptpath" in text
    for forbidden in ("unity", "run-windows", "quest", "reconstruct", "manager.start"):
        assert forbidden not in text
