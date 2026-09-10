from pathlib import Path

SCRIPT = Path("rescue-adopt-throughput-after-wrapper-output-bug.ps1").read_text(encoding="utf-8")
INTERNAL = Path("start-throughput-candidate-from-ab-plan-internal.ps1").read_text(encoding="utf-8")
WRAPPER = Path("start-throughput-candidate-from-ab-plan.ps1").read_text(encoding="utf-8")


def test_rescue_requires_exact_existing_job_and_plan_authority() -> None:
    assert "existing throughput candidate run plan" in SCRIPT
    assert "bodyrig-throughput-candidate-run-plan" in SCRIPT
    assert "source_enqueue_authority" in SCRIPT
    assert "bodyrig-body-build-source-enqueue-authority" in SCRIPT
    assert "candidate_job_id" in SCRIPT
    assert "candidate_run_plan_sha256" in SCRIPT
    assert "bodyrig-throughput-pbr-human-review-gate" in SCRIPT
    assert "pbr_stable_evidence_fingerprint_sha256" in SCRIPT


def test_rescue_is_non_destructive_and_comparison_only() -> None:
    assert "Try-CancelCandidateJob" not in SCRIPT
    assert "cancel" not in SCRIPT.lower()
    assert "comparison_only = $true" in SCRIPT
    assert "physical_acceptance_authority = $false" in SCRIPT
    assert "promotion_authority = $false" in SCRIPT
    assert "production_activation = $false" in SCRIPT
    assert "Write-CreateOnlyJson" in SCRIPT


def test_rescue_requires_exact_candidate_checkout_and_live_service() -> None:
    assert "branch --show-current" in SCRIPT
    assert "status --porcelain" in SCRIPT
    assert "/api/v1/operator-authority" in SCRIPT
    assert "/api/v1/jobs/$CandidateJobId" in SCRIPT
    assert "throughput_candidate_revision" in SCRIPT


def test_root_cause_is_captured_by_contract() -> None:
    # The internal launcher invokes the updater directly, so updater success-stream
    # items can bubble through to the wrapper. The wrapper then incorrectly
    # requires the complete captured stream to contain exactly one item.
    assert '& $updateScript -Branch $throughputRef -NoBrowser -SkipPlan' in INTERNAL
    assert '$raw = @(& $internal @internalParams)' in WRAPPER
    assert '$raw.Count -ne 1' in WRAPPER
