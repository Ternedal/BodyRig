from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "compare-recovery-throughput.ps1").read_text(encoding="utf-8")


def test_wrapper_resolves_exact_bodyrig_job_ids() -> None:
    assert "^job-[0-9a-f]{32}$" in SCRIPT
    assert '"BodyRig\\ui-jobs"' in SCRIPT
    assert '"job.json"' in SCRIPT
    assert "BaselineJobId" in SCRIPT
    assert "CandidateJobId" in SCRIPT


def test_wrapper_uses_the_same_bodyrig_data_root_for_jobs_and_people() -> None:
    assert "$env:BODYRIG_DATA_DIR" in SCRIPT
    assert 'Join-Path $env:BODYRIG_DATA_DIR "ui-jobs"' in SCRIPT
    assert '$personRoot = Join-Path $dataRoot "people"' in SCRIPT
    assert '"--person-root", $personRoot' in SCRIPT


def test_wrapper_invokes_canonical_throughput_audit_module() -> None:
    assert '"-m", "bodyrig.recovery_throughput_audit"' in SCRIPT
    assert '"--out"' in SCRIPT
    assert '".venv\\Scripts\\python.exe"' in SCRIPT


def test_wrapper_never_mutates_jobs_or_promotes_candidate() -> None:
    for token in (
        "Stop-Process",
        "Start-Process",
        "Remove-Item",
        "Move-Item",
        "Set-Content",
        "Add-Content",
        "git checkout",
        "git reset",
        "production_activation = $true",
    ):
        assert token not in SCRIPT
    assert "human visual review remains mandatory" in SCRIPT
    assert "no promotion authority was granted" in SCRIPT
