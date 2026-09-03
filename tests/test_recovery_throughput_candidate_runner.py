from __future__ import annotations

from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "run-recovery-throughput-candidate.ps1").read_text(encoding="utf-8")
BASELINE = "76c64a9546238663dedf750a1da4a230cc1e7fa4"


def test_candidate_runner_refuses_uncapped_baseline_and_requires_clean_checkout() -> None:
    assert f'$BaselineRevision = "{BASELINE}"' in SCRIPT
    assert "$head -ceq $BaselineRevision" in SCRIPT
    assert "Candidate runner refuses the uncapped baseline authority" in SCRIPT
    assert "status --porcelain" in SCRIPT
    assert "Candidate checkout is dirty" in SCRIPT


def test_candidate_runner_requires_versioned_sampling_authority() -> None:
    assert '$ExpectedSamplingRevision = "15fps-v1"' in SCRIPT
    assert "RECOVERY_TEMPORAL_SAMPLING_REVISION" in SCRIPT
    assert "$samplingRevision -cne $ExpectedSamplingRevision" in SCRIPT
    assert "Candidate recovery sampling authority mismatch" in SCRIPT


def test_candidate_runner_proves_running_service_matches_exact_current_head_before_post() -> None:
    assert 'BodyRig\\ui-service.json' in SCRIPT
    assert "$stateRevision -cne $Revision" in SCRIPT
    assert "Get-Process -Id $statePid" in SCRIPT
    assert "Assert-RunningServiceAuthority -Root $RepoRoot -Revision $head" in SCRIPT
    assert SCRIPT.index("Assert-RunningServiceAuthority -Root $RepoRoot -Revision $head") < SCRIPT.index(
        'Invoke-BodyRigJson -Method Post -Path "/api/v1/people/$PersonId/body/build"'
    )


def test_candidate_runner_starts_body_only_and_binds_job_to_exact_candidate_head() -> None:
    assert '$request = @{ feedback = ""; changes = @() }' in SCRIPT
    assert 'Invoke-BodyRigJson -Method Post -Path "/api/v1/people/$PersonId/body/build"' in SCRIPT
    assert '$jobRevision -cne $head' in SCRIPT
    assert "/personality/" not in SCRIPT
    assert "/voice/" not in SCRIPT


def test_candidate_runner_requires_health_stash_binding_and_no_active_body_job() -> None:
    assert 'Path "/api/v1/health"' in SCRIPT
    assert 'Path "/api/v1/stash/health"' in SCRIPT
    assert 'Path "/api/v1/people/$PersonId"' in SCRIPT
    assert 'Path "/api/v1/jobs?person_id=$PersonId"' in SCRIPT
    assert "A body-build is already active" in SCRIPT


def test_candidate_runner_uses_monitor_and_only_succeeds_on_terminal_success() -> None:
    assert 'Join-Path $RepoRoot "watch-body-build.ps1"' in SCRIPT
    assert 'Path "/api/v1/jobs/$jobId"' in SCRIPT
    assert '$finalStatus -ne "succeeded"' in SCRIPT
    assert "diagnostic_tail" in SCRIPT
    assert "compare-recovery-throughput-auto.ps1" in SCRIPT


def test_candidate_runner_has_no_checkout_or_process_mutation_commands() -> None:
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
