from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "compare-recovery-throughput.ps1").read_text(encoding="utf-8")


def test_wrapper_uses_bodyrig_storage_authority_and_exact_job_ids() -> None:
    assert "BODYRIG_DATA_DIR" in SCRIPT
    assert 'Join-Path $dataRoot "ui-jobs"' in SCRIPT
    assert 'Join-Path $dataRoot "people"' in SCRIPT
    assert "BaselineJobId" in SCRIPT
    assert "CandidateJobId" in SCRIPT
    assert "bodyrig.recovery_throughput_sampling_audit" in SCRIPT


def test_wrapper_binds_candidate_to_exact_clean_checkout_head() -> None:
    assert "git -C $RepoRoot status --porcelain" in SCRIPT
    assert "git -C $RepoRoot rev-parse HEAD" in SCRIPT
    assert "checkout has local changes" in SCRIPT
    assert '"--candidate-bodyrig-revision", $candidateBodyRigRevision' in SCRIPT
    assert "^[0-9a-f]{40}$" in SCRIPT


def test_wrapper_is_read_only_except_optional_create_only_audit_report_owned_by_python() -> None:
    forbidden = (
        "Remove-Item",
        "Set-Content",
        "Add-Content",
        "Stop-Process",
        "Start-Process",
        "git checkout",
        "git reset",
        "git clean",
        "Move-Item",
        "Copy-Item",
    )
    for token in forbidden:
        assert token not in SCRIPT
    assert '"--out"' in SCRIPT
