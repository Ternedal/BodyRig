from pathlib import Path


SCRIPT = (Path(__file__).resolve().parents[1] / "build-recovery-throughput-review-bundle.ps1").read_text(encoding="utf-8")


def test_wrapper_binds_bundle_to_clean_candidate_head_and_bodyrig_storage_authority() -> None:
    assert "rev-parse HEAD" in SCRIPT
    assert "status --porcelain" in SCRIPT
    assert "Candidate checkout is dirty" in SCRIPT
    assert "BODYRIG_DATA_DIR" in SCRIPT
    assert 'Join-Path $dataRoot "ui-jobs"' in SCRIPT
    assert 'Join-Path $dataRoot "people"' in SCRIPT
    assert "--expected-candidate-bodyrig-revision $head" in SCRIPT
    assert "bodyrig.recovery_throughput_review_bundle" in SCRIPT


def test_wrapper_only_reads_existing_jobs_and_creates_one_new_bundle() -> None:
    assert "BaselineJobId" in SCRIPT
    assert "CandidateJobId" in SCRIPT
    assert 'Test-Path -LiteralPath (Join-Path $baselineRoot "job.json")' in SCRIPT
    assert 'Test-Path -LiteralPath (Join-Path $candidateRoot "job.json")' in SCRIPT
    assert 'Join-Path $dataRoot "recovery-throughput-reviews"' in SCRIPT
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
        "/body/build",
        "/voice/",
        "/personality/",
    )
    for token in forbidden:
        assert token not in SCRIPT


def test_wrapper_never_claims_review_or_production_authority() -> None:
    assert "promotion/production remain false" in SCRIPT
    assert "review bundle: READY" in SCRIPT
    assert "PASS" not in SCRIPT.split('Write-Host "BodyRig recovery throughput review bundle: READY"')[-1]
