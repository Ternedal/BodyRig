from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "start-throughput-candidate-from-ab-plan.ps1").read_text(encoding="utf-8")


def test_launcher_requires_shared_plan_and_succeeded_retained_baseline() -> None:
    assert 'bodyrig-dual-candidate-ab-baseline-plan' in SCRIPT
    assert 'bodyrig.pbr_ab_body_job_source' in SCRIPT
    assert '--expected-revision", $mainRevision' in SCRIPT
    assert 'safe_source_lineage_passed' in SCRIPT
    assert 'baselineSource.person_id -ne $personId' in SCRIPT
    assert 'baselineSource.bodyrig_revision -ne $mainRevision' in SCRIPT


def test_launcher_revalidates_exact_live_candidate_contract_before_switch() -> None:
    assert 'bodyrig.ab_baseline_candidates' in SCRIPT
    assert '--expected-main-revision", $mainRevision' in SCRIPT
    assert '--expected-pbr-revision", $pbrRevision' in SCRIPT
    assert '--expected-throughput-revision", $throughputRevision' in SCRIPT
    assert 'candidateAuthority.candidates.pbr_v2.ref -ne $pbrRef' in SCRIPT
    assert 'candidateAuthority.candidates.recovery_throughput_v3.ref -ne $throughputRef' in SCRIPT
    assert 'candidateAuthority.contract_sha256' in SCRIPT
    assert 'candidate/skin-pbr-v2-current-main-20260908' not in SCRIPT
    assert 'candidate/recovery-throughput-v3-current-main-20260908' not in SCRIPT


def test_launcher_switches_service_and_starts_exact_non_retained_candidate() -> None:
    assert 'update-windows.ps1' in SCRIPT
    assert '& $updateScript -Branch $throughputRef -NoBrowser -SkipPlan' in SCRIPT
    assert 'if ($LASTEXITCODE -ne 0) {\n    throw "Could not update/restart BodyRig' not in SCRIPT
    assert 'start-revision-bound-body-build.ps1' in SCRIPT
    assert '& $startScript -PersonId $personId -BaseUri $BaseUri' in SCRIPT
    assert 'started.ab_baseline_retention' in SCRIPT
    assert '$null -ne $started.ab_baseline_retention' in SCRIPT
    assert '/api/v1/operator-authority' in SCRIPT


def test_launcher_post_enqueue_rechecks_refs_and_cancels_on_drift() -> None:
    assert '+refs/heads/main:refs/remotes/origin/main' in SCRIPT
    assert '+refs/heads/${throughputRef}:refs/remotes/origin/${throughputRef}' in SCRIPT
    assert 'origin/main moved after baseline plan creation' in SCRIPT
    assert 'throughput candidate ref moved after baseline plan creation' in SCRIPT
    assert '/api/v1/jobs/$JobId/cancel' in SCRIPT
    assert 'Job $candidateJobId is NOT A/B candidate-run authority' in SCRIPT


def test_candidate_run_receipt_is_create_only_and_non_activating() -> None:
    assert 'format = "bodyrig-throughput-candidate-run-plan"' in SCRIPT
    assert 'baseline_plan_sha256 = $planSha256' in SCRIPT
    assert 'baseline_job_json_sha256 = [string]$baselineSource.job_json_sha256' in SCRIPT
    assert 'candidate_workspace_retained = $false' in SCRIPT
    assert 'Write-CreateOnlyJson' in SCRIPT
    assert 'comparison_only = $true' in SCRIPT
    assert 'human_visual_authority_required = $true' in SCRIPT
    assert 'physical_acceptance_authority = $false' in SCRIPT
    assert 'promotion_authority = $false' in SCRIPT
    assert 'production_activation = $false' in SCRIPT


def test_launcher_prints_exact_candidate_owned_machine_ab_command() -> None:
    assert 'compare-recovery-throughput.ps1' in SCRIPT
    assert "-BaselineJobId '$BaselineJobId'" in SCRIPT
    assert "-CandidateJobId '$candidateJobId'" in SCRIPT
    assert "-BaselineBodyRigRevision '$mainRevision'" in SCRIPT
    assert 'build the immutable review bundle' in SCRIPT
