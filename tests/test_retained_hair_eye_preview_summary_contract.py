from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-retained-hair-eye-preview.ps1"


def test_retained_preview_summary_is_create_only_review_evidence() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert '$summaryPath = Join-Path $attempt "retained-hair-eye-preview.json"' in text
    assert 'format = "bodyrig-retained-hair-eye-preview"' in text
    assert 'semantics = "retained-reconstruction-hair-eye-physical-preview-not-full-fidelity-acceptance"' in text
    assert "Move-Item -LiteralPath $attempt -Destination $OutputRoot" in text
    assert 'throw "Retained hair+eye preview output already exists: $OutputRoot"' in text
