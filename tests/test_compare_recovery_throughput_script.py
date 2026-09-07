from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "compare-recovery-throughput.ps1").read_text(encoding="utf-8")


def test_wrapper_requires_explicit_baseline_and_exact_clean_candidate_checkout() -> None:
    assert "[string]$BaselineBodyRigRevision" in SCRIPT
    assert "ValidatePattern('^[0-9a-fA-F]{40}$')" in SCRIPT
    assert "git -C $RepoRoot status --porcelain" in SCRIPT
    assert "git -C $RepoRoot rev-parse HEAD" in SCRIPT
    assert '"--baseline-bodyrig-revision", $baselineBodyRigRevision' in SCRIPT
    assert '"--candidate-bodyrig-revision", $candidateBodyRigRevision' in SCRIPT
    assert "Baseline and candidate BodyRig revisions are identical" in SCRIPT


def test_wrapper_has_no_historical_baseline_or_branch_authority() -> None:
    assert "0b8f61b6f369e0d63ed006d808e316798121f79f" not in SCRIPT
    assert "agent/person-studio-photoreal-20260902" not in SCRIPT
    assert "agent/recovery-throughput-v3-20260903" not in SCRIPT
    assert "update-windows.ps1" not in SCRIPT


def test_wrapper_is_read_only_except_optional_create_only_audit_output_owned_by_python() -> None:
    for command in ("Remove-Item", "Set-Content", "Out-File", "Move-Item", "Copy-Item"):
        assert command not in SCRIPT
    assert '"--out"' in SCRIPT
    assert "bodyrig.recovery_throughput_sampling_audit" in SCRIPT
