from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REANALYSIS = ROOT / "run-fidelity-v5-reanalysis.ps1"
DIAGNOSTICS = ROOT / "run-fidelity-silhouette-diagnostics.ps1"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_v5_reanalysis_publishes_only_after_successful_staging() -> None:
    source = _source(REANALYSIS)
    assert ".reanalysis-v5-$tag-" in source
    assert "$published = $false" in source
    assert "Move-Item -LiteralPath $stagingRoot -Destination $outputRoot" in source
    assert "$published = $true" in source
    assert "if (-not $published -and (Test-Path -LiteralPath $stagingRoot))" in source
    assert "Remove-Item -LiteralPath $stagingRoot -Recurse -Force" in source


def test_silhouette_diagnostics_publishes_only_after_successful_staging() -> None:
    source = _source(DIAGNOSTICS)
    assert ".silhouette-diagnostics-$tag-" in source
    assert "$published = $false" in source
    assert "Move-Item -LiteralPath $stagingRoot -Destination $outputRoot" in source
    assert "$published = $true" in source
    assert "if (-not $published -and (Test-Path -LiteralPath $stagingRoot))" in source
    assert "Remove-Item -LiteralPath $stagingRoot -Recurse -Force" in source


def test_final_authority_paths_remain_commit_tagged() -> None:
    reanalysis = _source(REANALYSIS)
    diagnostics = _source(DIAGNOSTICS)
    assert 'Join-Path $WorkRoot "reanalysis-v5-$tag"' in reanalysis
    assert 'Join-Path $WorkRoot ("silhouette-diagnostics-" + $tag)' in diagnostics
