from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "run-recovery-throughput-baseline.ps1").read_text(encoding="utf-8")
BASELINE = "76c64a9546238663dedf750a1da4a230cc1e7fa4"


def test_runner_is_pinned_to_exact_uncapped_person_studio_authority() -> None:
    assert f'$ExpectedBaselineRevision = "{BASELINE}"' in SCRIPT
    assert "rev-parse HEAD" in SCRIPT
    assert "$head -cne $ExpectedBaselineRevision" in SCRIPT
    assert "status --porcelain" in SCRIPT
    assert "Baseline checkout is dirty" in SCRIPT


def test_runner_proves_running_service_root_revision_and_pid_before_starting_job() -> None:
    assert 'BodyRig\\ui-service.json' in SCRIPT
    assert '"bodyrig-ui-service"' in SCRIPT
    assert "$stateRoot -cne [System.IO.Path]::GetFullPath($Root)" in SCRIPT
    assert "$stateRevision -cne $Revision" in SCRIPT
    assert "Get-Process -Id $statePid" in SCRIPT
    assert SCRIPT.index("Assert-RunningServiceAuthority") < SCRIPT.index('Invoke-BodyRigJson -Method Post -Path "/api/v1/people/$PersonId/body/build"')


def test_runner_requires_health_stash_person_binding_and_no_active_body_job() -> None:
    assert 'Path "/api/v1/health"' in SCRIPT
    assert 'Path "/api/v1/stash/health"' in SCRIPT
    assert 'Path "/api/v1/people/$PersonId"' in SCRIPT
    assert '"stash_performer"' in SCRIPT
    assert 'Path "/api/v1/jobs?person_id=$PersonId"' in SCRIPT
    assert '@("queued", "running")' in SCRIPT
    assert "A body-build is already active" in SCRIPT


def test_runner_starts_body_only_job_and_verifies_persisted_job_authority() -> None:
    assert '$request = @{ feedback = ""; changes = @() }' in SCRIPT
    assert 'Invoke-BodyRigJson -Method Post -Path "/api/v1/people/$PersonId/body/build"' in SCRIPT
    assert '$jobRevision = [string](Get-Prop $job "bodyrig_revision" "")' in SCRIPT
    assert "$jobRevision -cne $ExpectedBaselineRevision" in SCRIPT
    assert "/personality/" not in SCRIPT
    assert "/voice/" not in SCRIPT


def test_runner_uses_canonical_monitor_and_only_succeeds_on_terminal_succeeded_state() -> None:
    assert 'Join-Path $RepoRoot "watch-body-build.ps1"' in SCRIPT
    assert 'Path "/api/v1/jobs/$jobId"' in SCRIPT
    assert '$finalStatus -ne "succeeded"' in SCRIPT
    assert "diagnostic_tail" in SCRIPT
    assert "A/B baseline: SUCCEEDED" in SCRIPT


def test_runner_is_operator_read_only_except_for_the_explicit_body_build_api_call() -> None:
    forbidden = (
        "git checkout",
        "git reset",
        "git clean",
        "git fetch",
        "Stop-Process",
        "Start-Process",
        "Remove-Item",
        "Set-Content",
        "Add-Content",
        "Move-Item",
        "Copy-Item",
    )
    for token in forbidden:
        assert token not in SCRIPT


def test_temp_bootstrap_can_target_baseline_checkout_via_repo_root() -> None:
    assert '$RepoRoot = (Get-Location).Path' in SCRIPT
    assert "$PSScriptRoot" not in SCRIPT
