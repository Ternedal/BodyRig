from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-fidelity-v5-review.ps1"


def source() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_review_pins_git_head_for_both_cheap_stages() -> None:
    text = source()
    assert "function Get-Head" in text
    assert "function Assert-HeadPinned" in text
    assert "$pinnedHead = Get-Head -RepoRoot $repoRoot" in text
    assert 'throw "BodyRig checkout changed during fidelity review:' in text
    assert text.count("Assert-HeadPinned -RepoRoot $repoRoot -Expected $pinnedHead") >= 5


def test_review_reuses_complete_reanalysis_and_diagnostics() -> None:
    text = source()
    assert "function Test-ReanalysisComplete" in text
    assert "function Test-DiagnosticsComplete" in text
    assert 'Write-Host "Reusing complete v5 reanalysis: $reanalysisOutput"' in text
    assert 'Write-Host "Reusing complete silhouette diagnostics: $diagnosticOutput"' in text
    for name in (
        "iteration-01-baseline.json",
        "iteration-02-refit1.json",
        "iteration-03-reconstruction2.json",
        "convergence-decision.json",
    ):
        assert name in text
    for label in ("baseline", "refit1", "reconstruction2"):
        assert label in text
    assert "silhouette-diagnostic.json" in text


def test_review_only_removes_incomplete_cheap_outputs() -> None:
    text = source()
    reanalysis_test = text.index("if (Test-ReanalysisComplete -Path $reanalysisOutput)")
    reanalysis_remove = text.index("Remove-Item -LiteralPath $reanalysisOutput -Recurse -Force")
    diagnostic_test = text.index("if (Test-DiagnosticsComplete -Path $diagnosticOutput)")
    diagnostic_remove = text.index("Remove-Item -LiteralPath $diagnosticOutput -Recurse -Force")
    assert reanalysis_test < reanalysis_remove
    assert diagnostic_test < diagnostic_remove
    assert "Unity" in text
    assert "SiTH" in text


def test_review_always_prints_persisted_score_and_mask_summary() -> None:
    text = source()
    assert "$scoreRows = foreach ($spec in $scoreSpecs)" in text
    assert "$diagnosticRows = foreach ($label in" in text
    assert '$scoreRows | Format-Table -AutoSize' in text
    assert '$diagnosticRows | Format-Table -AutoSize' in text
    assert 'Write-Host "Best iteration: $($decision.best_iteration)"' in text
    assert 'Write-Host "Best overall:   $($decision.best_overall)"' in text
    assert 'Write-Host "Next focus:     $($decision.next_focus)"' in text
