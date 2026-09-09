from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (ROOT / "start-throughput-candidate-from-ab-plan.ps1").read_text(encoding="utf-8")
INTERNAL = (ROOT / "start-throughput-candidate-from-ab-plan-internal.ps1").read_text(encoding="utf-8")


def test_internal_launcher_preserves_shared_plan_and_succeeded_retained_baseline_contract() -> None:
    assert 'bodyrig-dual-candidate-ab-baseline-plan' in INTERNAL
    assert 'bodyrig.pbr_ab_body_job_source' in INTERNAL
    assert '--expected-revision", $mainRevision' in INTERNAL
    assert 'safe_source_lineage_passed' in INTERNAL
    assert 'baselineSource.person_id -ne $personId' in INTERNAL
    assert 'baselineSource.bodyrig_revision -ne $mainRevision' in INTERNAL


def test_internal_launcher_revalidates_exact_live_candidate_contract_before_switch() -> None:
    assert 'bodyrig.ab_baseline_candidates' in INTERNAL
    assert '--expected-main-revision", $mainRevision' in INTERNAL
    assert '--expected-pbr-revision", $pbrRevision' in INTERNAL
    assert '--expected-throughput-revision", $throughputRevision' in INTERNAL
    assert 'candidateAuthority.candidates.pbr_v2.ref -ne $pbrRef' in INTERNAL
    assert 'candidateAuthority.candidates.recovery_throughput_v3.ref -ne $throughputRef' in INTERNAL
    assert 'candidateAuthority.contract_sha256' in INTERNAL
    assert 'candidate/skin-pbr-v2-current-main-20260908' not in INTERNAL
    assert 'candidate/recovery-throughput-v3-current-main-20260908' not in INTERNAL


def test_internal_launcher_switches_service_and_starts_exact_non_retained_candidate() -> None:
    assert 'update-windows.ps1' in INTERNAL
    assert '& $updateScript -Branch $throughputRef -NoBrowser -SkipPlan' in INTERNAL
    assert 'start-revision-bound-body-build.ps1' in INTERNAL
    assert '& $startScript -PersonId $personId -BaseUri $BaseUri' in INTERNAL
    assert 'started.ab_baseline_retention' in INTERNAL
    assert '$null -ne $started.ab_baseline_retention' in INTERNAL
    assert '/api/v1/operator-authority' in INTERNAL


def test_internal_launcher_post_enqueue_rechecks_refs_and_cancels_on_drift() -> None:
    assert '+refs/heads/main:refs/remotes/origin/main' in INTERNAL
    assert '+refs/heads/${throughputRef}:refs/remotes/origin/${throughputRef}' in INTERNAL
    assert 'origin/main moved after baseline plan creation' in INTERNAL
    assert 'throughput candidate ref moved after baseline plan creation' in INTERNAL
    assert '/api/v1/jobs/$JobId/cancel' in INTERNAL
    assert 'Job $candidateJobId is NOT A/B candidate-run authority' in INTERNAL


def test_internal_candidate_run_receipt_is_create_only_and_non_activating() -> None:
    assert 'format = "bodyrig-throughput-candidate-run-plan"' in INTERNAL
    assert 'baseline_plan_sha256 = $planSha256' in INTERNAL
    assert 'baseline_job_json_sha256 = [string]$baselineSource.job_json_sha256' in INTERNAL
    assert 'candidate_workspace_retained = $false' in INTERNAL
    assert 'Write-CreateOnlyJson' in INTERNAL
    assert 'comparison_only = $true' in INTERNAL
    assert 'human_visual_authority_required = $true' in INTERNAL
    assert 'physical_acceptance_authority = $false' in INTERNAL
    assert 'promotion_authority = $false' in INTERNAL
    assert 'production_activation = $false' in INTERNAL


def test_internal_launcher_prints_plan_bound_watcher_and_canonical_continuation() -> None:
    assert 'watch-throughput-candidate-from-ab-plan.ps1' in INTERNAL
    assert (
        'Write-Host "Monitor:            .\\watch-throughput-candidate-from-ab-plan.ps1 '
        '-BaselineJobId \'$BaselineJobId\' -CandidateJobId \'$candidateJobId\'"'
        in INTERNAL
    )
    assert 'continue-throughput-review-from-ab-plan.ps1' in INTERNAL
    assert "-BaselineJobId '$BaselineJobId'" in INTERNAL
    assert "-CandidateJobId '$candidateJobId'" in INTERNAL
    assert 'canonical plan-bound human-review command' in INTERNAL
    assert 'Write-Host "  .\\compare-recovery-throughput.ps1' not in INTERNAL
    assert 'Do not invoke compare-recovery-throughput.ps1, build-recovery-throughput-review-bundle.ps1, or record-recovery-throughput-human-review.ps1 directly for plan-bound evidence.' in INTERNAL


def test_canonical_launcher_requires_recorded_pbr_human_review_before_internal_launch() -> None:
    assert 'bodyrig.pbr_human_review_gate' in WRAPPER
    assert 'bodyrig\\pbr_human_review_gate.py' in WRAPPER
    assert 'start-throughput-candidate-from-ab-plan-internal.ps1' in WRAPPER
    assert 'Plan-bound PBR human review is exact and recorded.' in WRAPPER
    assert '& $internal @internalParams' in WRAPPER
    assert 'bodyrig-throughput-pbr-human-review-gate' in WRAPPER
    assert 'human_visual_authority_recorded = $true' in WRAPPER
    assert 'physical_acceptance_authority = $false' in WRAPPER
    assert 'promotion_authority = $false' in WRAPPER
    assert 'production_activation = $false' in WRAPPER


def test_canonical_launcher_pins_candidate_enqueue_to_reviewed_stash_performer() -> None:
    assert 'BODYRIG_PINNED_STASH_PERFORMER_ID' in WRAPPER
    assert '[string]$gateBefore.stash_performer_id' in WRAPPER
    assert '$candidateJob.source_enqueue_authority' in WRAPPER
    assert 'bodyrig-body-build-source-enqueue-authority' in WRAPPER
    assert '[string]$sourceAuthority.stash_performer_id -ne [string]$gateBefore.stash_performer_id' in WRAPPER
    assert 'stash_performer_id = [string]$gateAfter.stash_performer_id' in WRAPPER
    assert 'Throughput candidate did not preserve the PBR-reviewed Stash performer at enqueue' in WRAPPER


def test_canonical_launcher_source_pin_is_scoped_around_frozen_internal_launcher() -> None:
    set_index = WRAPPER.index('[Environment]::SetEnvironmentVariable("BODYRIG_PINNED_STASH_PERFORMER_ID", [string]$gateBefore.stash_performer_id')
    launch_index = WRAPPER.index('& $internal @internalParams')
    restore_index = WRAPPER.index('[Environment]::SetEnvironmentVariable("BODYRIG_PINNED_STASH_PERFORMER_ID", $oldPinnedPerformer')
    assert set_index < launch_index < restore_index
    assert 'BODYRIG_PINNED_STASH_PERFORMER_ID' not in INTERNAL


def test_canonical_launcher_cancels_and_removes_run_authority_if_pbr_gate_drifts() -> None:
    assert 'Assert-GateProbeStable -Before $gateBefore -After $gateAfter' in WRAPPER
    assert 'Try-CancelCandidateJob -JobId $candidateJobId' in WRAPPER
    assert 'Remove-Item -LiteralPath $runPlanPath -Force' in WRAPPER
    assert 'PBR human-review authority drifted while starting throughput candidate' in WRAPPER
    assert '$BaselineJobId-throughput-$candidateJobId-pbr-gate.json' in WRAPPER
