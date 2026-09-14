from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-retained-hair-eye-preview.ps1"


def test_retained_preview_hashes_inputs_before_and_after_work() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    before = text.index("$packageShaBefore = Sha256 $PackagePath")
    work = text.index('Write-Host "=== 1/5 SOURCE HAIR FROM RETAINED RECONSTRUCTION ==="')
    after = text.index("Retained reconstruction/package authority changed during hair+eye preview continuation.")
    publish = text.index("Move-Item -LiteralPath $attempt -Destination $OutputRoot")

    assert before < work < after < publish
