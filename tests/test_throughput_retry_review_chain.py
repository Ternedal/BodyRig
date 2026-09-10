from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTINUE = ROOT / "continue-throughput-retry-review.ps1"
RECORD = ROOT / "record-throughput-retry-human-review.ps1"


def test_retry_continuation_is_pinned_to_reviewed_fix_and_failed_run() -> None:
    text = CONTINUE.read_text(encoding="utf-8")
    assert "5fa01deb08399fda64e83db1329d4d2e83ad1bc2" in text
    assert "ec743446d98809d693d01e51830f435fc3c09535" in text
    assert "job-164250c1d8e04f66a8f8f6cf646c1a31" in text
    assert "_load_canonical_checkpoint() got an unexpected keyword argument 'source_fps'" in text
    assert "bodyrig-throughput-retry-after-resume-signature-fix" in text
    assert "bodyrig-throughput-retry-review-continuation" in text


def test_retry_continuation_delegates_machine_and_bundle_to_candidate_owned_tools() -> None:
    text = CONTINUE.read_text(encoding="utf-8")
    assert "compare-recovery-throughput.ps1" in text
    assert "build-recovery-throughput-review-bundle.ps1" in text
    assert "bodyrig.body_job_receipt_authority" in text
    assert "source_evidence_sha256" in text
    assert "source_files_sha256" in text
    assert "source_manifest_parity_verified = $true" in text
    assert "source_file_hashes_parity_verified = $true" in text
    assert "physical_acceptance_authority = $false" in text
    assert "promotion_authority = $false" in text
    assert "production_activation = $false" in text
    assert "continue-throughput-review-from-ab-plan.ps1" not in text


def test_retry_human_review_requires_explicit_visual_confirmation_and_exact_bundle() -> None:
    text = RECORD.read_text(encoding="utf-8")
    assert "[switch]$ConfirmVisualReview" in text
    assert "if (-not $ConfirmVisualReview)" in text
    assert "record-recovery-throughput-human-review.ps1" in text
    assert "continuation-authority.json" in text
    assert "review_bundle_receipt_sha256" in text
    assert "machine_audit_sha256" in text
    assert "bodyrig-throughput-retry-human-review-authority" in text
    assert "physical_acceptance_authority = $false" in text
    assert "promotion_authority = $false" in text
    assert "production_activation = $false" in text


def test_retry_review_chain_never_rewrites_original_plan_or_gate() -> None:
    continue_text = CONTINUE.read_text(encoding="utf-8")
    record_text = RECORD.read_text(encoding="utf-8")
    for text in (continue_text, record_text):
        assert "Set-Content -LiteralPath $sharedPlanPath" not in text
        assert "Set-Content -LiteralPath $oldGatePath" not in text
        assert "Move-Item -LiteralPath $sharedPlanPath" not in text
        assert "Move-Item -LiteralPath $oldGatePath" not in text
