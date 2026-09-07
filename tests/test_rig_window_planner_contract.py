from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "plan-rig-window.ps1").read_text(encoding="utf-8")
INTERRUPTED = (ROOT / "resume-interrupted-body-job.ps1").read_text(encoding="utf-8")


def test_rig_window_planner_requires_clean_checkout_bound_authority() -> None:
    assert "PowerShell 7+ (pwsh) is required" in SOURCE
    assert "git -C $repoRoot rev-parse HEAD" in SOURCE
    assert "git -C $repoRoot status --porcelain" in SOURCE
    assert "BodyRig checkout is dirty" in SOURCE
    assert "bodyrig.__file__" in SOURCE
    assert "unexpected location" in SOURCE


def test_rig_window_priority_is_reuse_before_reconstruction() -> None:
    rescue = SOURCE.index('path = "historical-gate-a-resume"')
    acceptance = SOURCE.index('path = "existing-gate-a-acceptance"')
    existing = SOURCE.index('path = "existing-physical-session"')
    interrupted = SOURCE.index('path = "interrupted-body-recovery"')
    fresh = SOURCE.index('path = "fresh-profiled-physical-preflight"')

    assert rescue < acceptance < existing < interrupted < fresh
    assert "bodyrig.resume_body_job $candidate.job_id --assess-only" in SOURCE
    assert "resume-interrupted-body-job.ps1" in SOURCE
    assert "-AssessOnly" in SOURCE
    assert 'expensive_reconstruction_rerun = $false' in SOURCE
    assert 'expensive_reconstruction_rerun = $true' in SOURCE
    assert "This physical body acceptance chain is already complete" in SOURCE


def test_planner_searches_both_ui_data_and_standalone_session_roots() -> None:
    assert '$dataRoot = [string]$env:BODYRIG_DATA_DIR' in SOURCE
    assert '$artifactBase = [string]$env:LOCALAPPDATA' in SOURCE
    assert 'Join-Path $artifactBase "BodyRig\\physical-clone-sessions"' in SOURCE
    assert 'Join-Path $dataRoot "physical-clone-sessions"' in SOURCE
    assert '$sessionRoots = @($standaloneSessionRoot, $dataSessionRoot) | Select-Object -Unique' in SOURCE
    assert 'foreach ($sessionsRoot in $sessionRoots)' in SOURCE


def test_planner_keeps_gate_a_resume_candidate_after_failed_retry() -> None:
    assert '$job.PSObject.Properties["resume_source_error"]' in SOURCE
    assert '$resumeSourceError = [string]$resumeSourceErrorProperty.Value' in SOURCE
    assert 'resume_source_error = $resumeSourceError' in SOURCE
    assert '$_.resume_source_error -like "*high-fidelity Gate A failed*"' in SOURCE


def test_interrupted_recovery_wrapper_uses_existing_bodyrig_service_authority() -> None:
    assert "$PSVersionTable.PSVersion.Major -lt 7" in INTERRUPTED
    assert "git -C $repoRoot rev-parse HEAD" in INTERRUPTED
    assert "git -C $repoRoot status --porcelain" in INTERRUPTED
    assert 'Invoke-RestMethod -Method Get -Uri "$baseUri/api/v1/health"' in INTERRUPTED
    assert '$health.PSObject.Properties["bodyrig_revision"]' in INTERRUPTED
    assert '"$baseUri/api/v1/jobs/$JobId/resume-status"' in INTERRUPTED
    assert '"$baseUri/api/v1/jobs/$JobId/resume"' in INTERRUPTED
    assert "$status.expensive_reconstruction_rerun -ne $false" in INTERRUPTED
    assert "$status.bodyrig_revision -ne $head" in INTERRUPTED
    assert "[switch]$AssessOnly" in INTERRUPTED


def test_planner_only_emits_mutating_next_commands() -> None:
    assert 'next_command = ".\\resume-body-job.ps1 -JobId' in SOURCE
    assert 'next_command = ".\\resume-interrupted-body-job.ps1 -JobId' in SOURCE
    assert '.\\bodyrig-status.ps1 -PerformerId' in SOURCE
    assert "& $python -m bodyrig.resume_body_job $candidate.job_id --assess-only" in SOURCE
    assert "& $interruptedResume -JobId $candidate.job_id -AssessOnly" in SOURCE
    assert "& .\\resume-body-job.ps1" not in SOURCE
    assert "clone-body-from-stash-ready.ps1" not in SOURCE
