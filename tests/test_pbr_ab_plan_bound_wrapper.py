from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (ROOT / "run-pbr-ab-from-body-job.ps1").read_text(encoding="utf-8")
INTERNAL = (ROOT / "run-pbr-ab-from-body-job-internal.ps1").read_text(encoding="utf-8")


def test_canonical_wrapper_requires_shared_baseline_plan() -> None:
    assert 'BodyRig\\ab-baseline-plans\\$BaselineJobId.json' in WRAPPER
    assert 'bodyrig-dual-candidate-ab-baseline-plan' in WRAPPER
    assert 'candidate_contract_sha256' in WRAPPER
    assert 'retained_reconstruction_reuse' in WRAPPER
    assert 'separate_candidate_body_build_required' in WRAPPER
    assert '$CandidateRef -ne $pbrRef' in WRAPPER


def test_candidate_byte_contract_is_validated_before_and_after_pbr_run() -> None:
    assert 'bodyrig.ab_baseline_candidates' in WRAPPER
    assert '--expected-main-revision' in WRAPPER
    assert '--expected-pbr-revision' in WRAPPER
    assert '--expected-throughput-revision' in WRAPPER
    before = WRAPPER.index('$before = Validate-CandidateAuthority')
    invoke = WRAPPER.index('& $internal @internalArgs')
    after = WRAPPER.index('$after = Validate-CandidateAuthority')
    publish = WRAPPER.index('Write-CreateOnlyJson -Path $planAuthorityPath')
    assert before < invoke < after < publish


def test_existing_body_job_pbr_implementation_is_preserved_as_internal_step() -> None:
    assert 'run-pbr-ab-from-body-job-internal.ps1' in WRAPPER
    assert 'run-pbr-ab-physical-review.ps1' in INTERNAL
    assert 'bodyrig.pbr_ab_body_job_source' in INTERNAL
    assert 'body-job-source-authority.json' in INTERNAL


def test_plan_bound_wrapper_forces_known_output_and_checks_run_revisions() -> None:
    assert '"-OutputDir",$OutputDir' in WRAPPER
    assert '[string]$runAuthority.format -ne "bodyrig-pbr-ab-run"' in WRAPPER
    assert '([string]$runAuthority.baseline_revision).ToLowerInvariant() -ne $mainRevision' in WRAPPER
    assert '([string]$runAuthority.candidate_revision).ToLowerInvariant() -ne $pbrRevision' in WRAPPER
    assert 'body-job-plan-authority.json' in WRAPPER
    assert 'format = "bodyrig-pbr-ab-body-job-plan-authority"' in WRAPPER
    assert 'baseline_plan_sha256 = $planSha256' in WRAPPER
    assert 'run_authority_sha256' in WRAPPER
    assert 'source_authority_sha256' in WRAPPER


def test_plan_authority_remains_comparison_only_and_non_activating() -> None:
    assert 'comparison_only = $true' in WRAPPER
    assert 'human_visual_authority_required = $true' in WRAPPER
    assert 'physical_acceptance_authority = $false' in WRAPPER
    assert 'promotion_authority = $false' in WRAPPER
    assert 'production_activation = $false' in WRAPPER


def test_post_run_live_contract_validation_happens_before_plan_authority_write() -> None:
    post = WRAPPER.index('-Label "post-run candidate authority"')
    run_read = WRAPPER.index('$runAuthority = Read-JsonObject')
    plan_write = WRAPPER.index('Write-CreateOnlyJson -Path $planAuthorityPath')
    assert post < run_read < plan_write
