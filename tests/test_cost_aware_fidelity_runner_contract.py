from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_runner_caps_expensive_rebuilds_and_exposes_wall_clock_budget() -> None:
    source = text("run-profiled-fidelity-convergence.ps1")
    assert "[int]$MaxFullRebuilds = 2" in source
    assert "[int]$MaxRefinementsPerRebuild = 3" in source
    assert "[double]$MaxWallClockHours = 8.0" in source
    assert "WallClockAllowsAnotherFullRebuild" in source
    assert 'stage = "full-reconstruction"' not in source  # stage is emitted via Update-Progress call, not static result evidence
    assert 'Update-Progress -NewStage "full-reconstruction"' in source
    assert "MaxIterations = 10" not in source


def test_refinement_reuses_sith_workspace_instead_of_calling_clone_pipeline() -> None:
    source = text("refit-fidelity-candidate.ps1")
    assert "bodyrig.external_fitter_cli" in source
    assert "--identity-workspace" in source
    assert "bodyrig.bodyprint_adjustment" in source
    assert "reconstruction.json" in source
    assert "reconstructionShaBefore" in source
    assert "reconstructionShaAfter" in source
    assert "expensive_reconstruction_rerun = $false" in source
    assert "clone-body-from-stash" not in source
    assert "bodyrig.recover_cli" not in source
    assert "identity_capture_cli" not in source


def test_direct_refit_rendering_is_explicitly_comparison_only() -> None:
    source = text("run-fidelity-windows-render-probe.ps1")
    assert "Pass exactly one of -AcceptanceDir, -PackagePath or -ReviewRuntimeDir" in source
    assert "bodyrig.materialize_cli" in source
    assert 'comparisonAuthority = "validated-package-comparison-only"' in source
    assert "physical_acceptance_authority = $usingAcceptance" in source
    assert "comparison_only = $true" in source
    assert "production_activation = $false" in source
    assert "complete-reference-renderer-acceptance" not in source


def test_runner_writes_live_progress_best_preview_and_never_auto_activates() -> None:
    source = text("run-profiled-fidelity-convergence.ps1")
    assert 'progress.json' in source
    assert 'best-preview' in source
    assert 'observed_full_rebuild_seconds_average' in source
    assert 'observed_refinement_seconds_average' in source
    assert 'human_visual_authority_required = $true' in source
    assert 'production_activation = $false' in source
    assert 'complete-acceptance.ps1' not in source
    assert 'complete-reference-renderer-acceptance' not in source


def test_watcher_is_read_only_and_shows_quality_and_compute_progress() -> None:
    source = text("watch-fidelity-progress.ps1")
    assert 'progress.json' in source
    assert 'full rebuilds:' in source
    assert 'cheap refits:' in source
    assert 'Budget ETA:' in source
    assert 'human_plausibility' in source
    assert 'photorealism' in source
    assert 'Start-Sleep' in source
    assert 'Set-Content' not in source
    assert 'Remove-Item' not in source
