from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (ROOT / "record-throughput-human-review-from-ab-plan.ps1").read_text(encoding="utf-8")
INTERNAL = (ROOT / "record-throughput-human-review-from-ab-plan-internal.ps1").read_text(encoding="utf-8")
CONTINUATION = (ROOT / "continue-throughput-review-from-ab-plan.ps1").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "THROUGHPUT_PLAN_BOUND_REVIEW.md").read_text(encoding="utf-8")


def test_internal_plan_bound_human_review_consumes_exact_continuation_and_plans() -> None:
    assert 'bodyrig-throughput-plan-bound-review-continuation' in INTERNAL
    assert 'bodyrig-dual-candidate-ab-baseline-plan' in INTERNAL
    assert 'bodyrig-throughput-candidate-run-plan' in INTERNAL
    assert 'baseline_plan_sha256' in INTERNAL
    assert 'candidate_run_plan_sha256' in INTERNAL
    assert 'candidate_contract_sha256' in INTERNAL
    assert 'continuation-authority.json' in INTERNAL
    assert 'contracts\\ab-baseline-candidates-v1.json' in INTERNAL
    assert 'Pass -ConfirmVisualReview only after visually comparing all four canonical baseline/candidate views.' in INTERNAL


def test_internal_plan_bound_human_review_requires_exact_candidate_checkout_and_remote_refs() -> None:
    assert 'branch --show-current' in INTERNAL
    assert 'Plan-bound throughput human review must run from candidate branch $CandidateRef.' in INTERNAL
    assert 'status --porcelain' in INTERNAL
    assert '+refs/heads/main:refs/remotes/origin/main' in INTERNAL
    assert '+refs/heads/${CandidateRef}:refs/remotes/origin/${CandidateRef}' in INTERNAL
    assert 'origin/main moved after throughput continuation authority was created.' in INTERNAL
    assert 'Throughput candidate ref moved after continuation authority was created.' in INTERNAL


def test_internal_plan_bound_human_review_replays_persisted_body_job_authority() -> None:
    assert 'bodyrig.body_job_receipt_authority' in INTERNAL
    assert 'bodyrig\\body_job_receipt_authority.py' in INTERNAL
    for field in (
        'baseline_source_binding_sha256',
        'candidate_source_binding_sha256',
        'baseline_body_review_sha256',
        'candidate_body_review_sha256',
        'source_evidence_sha256',
        'source_files_sha256',
        'source_manifest_parity_verified',
        'source_file_hashes_parity_verified',
    ):
        assert field in INTERNAL
    assert 'Assert-ReceiptMatchesContinuation -Probe $baselineAfter -Authority $continuation -Role baseline' in INTERNAL
    assert 'Assert-ReceiptMatchesContinuation -Probe $candidateAfter -Authority $continuation -Role candidate' in INTERNAL
    assert 'Assert-ReceiptMatchesContinuation -Probe $baselineTerminal -Authority $continuation -Role baseline' in INTERNAL
    assert 'Assert-ReceiptMatchesContinuation -Probe $candidateTerminal -Authority $continuation -Role candidate' in INTERNAL


def test_internal_plan_bound_human_review_binds_machine_and_immutable_bundle_bytes() -> None:
    assert 'machine-audit.json' in INTERNAL
    assert 'review-bundle.json' in INTERNAL
    assert 'Human review bundle machine-audit bytes do not match the machine audit bound by continuation authority.' in INTERNAL
    assert 'review_bundle_receipt_sha256' in INTERNAL
    assert 'machine_audit_sha256' in INTERNAL
    assert 'Invoke-HumanReviewVerify' in INTERNAL
    assert 'verify_review' in INTERNAL


def test_internal_plan_bound_human_review_isolates_candidate_owned_recorder() -> None:
    assert 'record-recovery-throughput-human-review.ps1' in INTERNAL
    assert 'Get-Command pwsh' in INTERNAL
    assert '& $pwsh.Source @childArgs' in INTERNAL
    assert 'Candidate-owned throughput human review recorder failed' in INTERNAL
    assert 'human_visual_review_completed -ne $true' in INTERNAL
    assert 'removed non-authoritative human receipt when present' in INTERNAL


def test_internal_plan_bound_human_review_publishes_create_only_intermediate_authority() -> None:
    assert 'format = "bodyrig-throughput-plan-bound-human-review-authority"' in INTERNAL
    assert 'continuation_authority_sha256 = $continuationSha' in INTERNAL
    assert 'human_review_sha256 = File-Sha256 -Path $humanReviewPath' in INTERNAL
    assert 'human_visual_authority_recorded = $true' in INTERNAL
    assert 'physical_acceptance_authority = $false' in INTERNAL
    assert 'promotion_authority = $false' in INTERNAL
    assert 'production_activation = $false' in INTERNAL
    assert 'Human review receipt changed before terminal authority publication.' in INTERNAL


def test_canonical_human_review_requires_pbr_to_throughput_gate_and_replays_pbr_authority() -> None:
    assert '$BaselineJobId-throughput-$CandidateJobId-pbr-gate.json' in WRAPPER
    assert 'bodyrig-throughput-pbr-human-review-gate' in WRAPPER
    assert 'bodyrig.pbr_human_review_gate' in WRAPPER
    assert 'record-throughput-human-review-from-ab-plan-internal.ps1' in WRAPPER
    assert 'Assert-GateMatchesProbe -Gate $gate -Probe $probeBefore' in WRAPPER
    assert 'candidate_run_plan_sha256' in WRAPPER
    assert 'pbr_human_review_authority_sha256' in WRAPPER
    assert 'pbr_human_review_sha256' in WRAPPER


def test_canonical_human_review_binds_exact_pbr_stash_performer_at_every_replay() -> None:
    assert '"baseline_job_id","person_id","stash_performer_id","baseline_plan_sha256"' in WRAPPER
    assert 'Assert-GateMatchesProbe -Gate $gate -Probe $probeBefore' in WRAPPER
    assert 'Assert-GateMatchesProbe -Gate $gate -Probe $probeAfter' in WRAPPER
    assert 'Assert-GateMatchesProbe -Gate $gate -Probe $terminalProbe' in WRAPPER
    assert 'PBR-to-throughput gate no longer matches PBR authority: $field' in WRAPPER


def test_canonical_human_review_publishes_pbr_sequenced_terminal_authority() -> None:
    assert 'format = "bodyrig-throughput-pbr-sequenced-human-review-authority"' in WRAPPER
    assert '$RunDir.pbr-sequenced-human-review-authority.json' in WRAPPER
    assert 'stash_performer_id = [string]$gate.stash_performer_id' in WRAPPER
    assert 'plan_bound_human_review_authority_sha256 = $intermediateSha' in WRAPPER
    assert 'pbr_human_visual_authority_recorded = $true' in WRAPPER
    assert 'human_visual_authority_recorded = $true' in WRAPPER
    assert 'physical_acceptance_authority = $false' in WRAPPER
    assert 'promotion_authority = $false' in WRAPPER
    assert 'production_activation = $false' in WRAPPER
    assert 'Sequenced throughput authority inputs changed before terminal publication.' in WRAPPER


def test_continuation_and_docs_keep_canonical_human_review_surface() -> None:
    assert 'record-throughput-human-review-from-ab-plan.ps1' in CONTINUATION
    assert 'record-throughput-human-review-from-ab-plan.ps1' in DOC
    assert 'record-recovery-throughput-human-review.ps1' in DOC
    assert 'candidate-owned' in DOC
    assert 'must not be invoked directly' in DOC
    assert 'continuation-authority.json' in DOC
