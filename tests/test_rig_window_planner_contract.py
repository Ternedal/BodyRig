from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "plan-rig-window.ps1").read_text(encoding="utf-8")


def test_rig_window_planner_requires_clean_checkout_bound_authority() -> None:
    assert "PowerShell 7+ (pwsh) is required" in SOURCE
    assert "git -C $repoRoot rev-parse HEAD" in SOURCE
    assert "git -C $repoRoot status --porcelain" in SOURCE
    assert "BodyRig checkout is dirty" in SOURCE
    assert "bodyrig.__file__" in SOURCE
    assert "unexpected location" in SOURCE


def test_rig_window_priority_is_reuse_before_reconstruction() -> None:
    rescue = SOURCE.index('path = "historical-gate-a-resume"')
    existing = SOURCE.index('path = "existing-physical-session"')
    fresh = SOURCE.index('path = "fresh-profiled-physical-preflight"')

    assert rescue < existing < fresh
    assert "bodyrig.resume_body_job $candidate.job_id --assess-only" in SOURCE
    assert 'persistent_mutation -eq $false' in SOURCE
    assert 'recovery_rerun = $false' in SOURCE
    assert 'fitter_rerun = $false' in SOURCE
    assert 'recovery_rerun = $true' in SOURCE
    assert 'fitter_rerun = $true' in SOURCE


def test_planner_only_emits_mutating_next_commands() -> None:
    assert 'next_command = ".\\resume-body-job.ps1 -JobId' in SOURCE
    assert '.\\bodyrig-status.ps1 -PerformerId' in SOURCE
    assert "& $python -m bodyrig.resume_body_job $candidate.job_id --assess-only" in SOURCE
    assert "& .\\resume-body-job.ps1" not in SOURCE
    assert "clone-body-from-stash-ready.ps1" not in SOURCE
