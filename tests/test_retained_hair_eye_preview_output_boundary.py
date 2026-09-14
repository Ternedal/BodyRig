from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-retained-hair-eye-preview.ps1"


def test_retained_preview_publishes_atomically_from_partial_directory() -> None:
    text = SCRIPT.read_text(encoding="utf-8")

    assert '".partial-" + [Guid]::NewGuid().ToString("N")' in text
    assert "$committed = $false" in text
    assert "Move-Item -LiteralPath $attempt -Destination $OutputRoot" in text
    assert "$committed = $true" in text
    assert "Remove-Item -LiteralPath $attempt -Recurse -Force -ErrorAction SilentlyContinue" in text
