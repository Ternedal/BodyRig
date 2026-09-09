from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = (ROOT / "record-throughput-human-review-from-ab-plan.ps1").read_text(encoding="utf-8")
CONTINUATION = (ROOT / "continue-throughput-review-from-ab-plan.ps1").read_text(encoding="utf-8")
DOC = (ROOT / "docs" / "THROUGHPUT_PLAN_BOUND_REVIEW.md").read_text(encoding="utf-8")


def test_plan_bound_human_review_consumes_exact_continuation_and_plans() -> None:
    assert 'bodyrig-throughput-plan-bound-review-continuation' in WRAPPER
    assert 'bodyrig-dual-candidate-ab-baseline-plan' in WRAPPER
    assert 'bodyrig-throughput-candidate-run-plan' in WRAPPER
    assert 'baseline_plan_sha256' in WRAPPER
    assert 'candidate_run_plan_sha256' in WRAPPER
    assert 'candidate_contract_sha256' in WRAPPER
    assert 'continuation-authority.json' in WRAPPER
    assert 'contracts\\ab-baseline-candidates-v1.json' in WRAPPER
    assert 'Pass -ConfirmVisualReview only after visually comparing all four canonical baseline/candidate views.' in WRAPPER


def test_plan_bound_human_review_requires_exact_candidate_checkout_and_remote_refs() -> None:
    assert 'branch --show-current' in WRAPPER
    assert 'Plan-bound throughput human review must run from candidate branch $CandidateRef.' in WRAPPER
    assert 'status --porcelain' in WRAPPER
    assert '+refs/heads/main:refs/remotes/origin/main' in WRAPPER
    assert '+refs/heads/${CandidateRef}:refs/remotes/origin/${CandidateRef}' in WRAPPER
    assert 'origin/main moved after throughput continuation authority was created.' in WRAPPER
    assert 'Throughput candidate ref moved after continuation authority was created.' in WRAPPER


def test_plan_bound_human_review_replays_persisted_body_job_authority() -> None:
    assert 'bodyrig.body_job_receipt_authority' in WRAPPER
    assert 'bodyrig\\body_job_receipt_authority.py' in WRAPPER
    assert '-JobId $BaselineJobId -ExpectedRevision $mainRevision -ExpectedPersonId $personId' in WRAPPER
    assert '-JobId $CandidateJobId -ExpectedRevision $throughputRevision -ExpectedPersonId $personId' in WRAPPER
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
        assert field in WRAPPER
    assert 'Assert-ReceiptMatchesContinuation -Probe $baselineAfter -Authority $continuation -Role baseline' in WRAPPER
    assert 'Assert-ReceiptMatchesContinuation -Probe $candidateAfter -Authority $continuation -Role candidate' in WRAPPER
    assert 'Assert-ReceiptMatchesContinuation -Probe $baselineTerminal -Authority $continuation -Role baseline' in WRAPPER
    assert 'Assert-ReceiptMatchesContinuation -Probe $candidateTerminal -Authority $continuation -Role candidate' in WRAPPER


def test_plan_bound_human_review_binds_machine_and_immutable_bundle_bytes() -> None:
    assert 'machine-audit.json' in WRAPPER
    assert 'review-bundle.json' in WRAPPER
    assert 'Human review bundle machine-audit bytes do not match the machine audit bound by continuation authority.' in WRAPPER
    assert 'review_bundle_receipt_sha256' in WRAPPER
    assert 'machine_audit_sha256' in WRAPPER
    assert 'Invoke-HumanReviewVerify' in WRAPPER
    assert 'verify_review' in WRAPPER


def test_plan_bound_human_review_isolates_candidate_owned_recorder() -> None:
    assert 'record-recovery-throughput-human-review.ps1' in WRAPPER
    assert 'Get-Command pwsh' in WRAPPER
    assert '& $pwsh.Source @childArgs' in WRAPPER
    assert 'candidate-owned throughput human review recorder failed' in WRAPPER
    assert 'human_visual_review_completed -ne $true' in WRAPPER
    assert 'removed non-authoritative human receipt when present' in WRAPPER


def test_plan_bound_human_review_publishes_create_only_terminal_authority() -> None:
    assert 'format = "bodyrig-throughput-plan-bound-human-review-authority"' in WRAPPER
    assert 'continuation_authority_sha256 = $continuationSha' in WRAPPER
    assert 'human_review_sha256 = File-Sha256 -Path $humanReviewPath' in WRAPPER
    assert 'human_visual_authority_recorded = $true' in WRAPPER
    assert 'physical_acceptance_authority = $false' in WRAPPER
    assert 'promotion_authority = $false' in WRAPPER
    assert 'production_activation = $false' in WRAPPER
    assert 'Refusing to overwrite plan-bound throughput human-review authority' in WRAPPER
    assert 'Human review receipt changed before terminal authority publication.' in WRAPPER


def test_continuation_and_docs_route_human_review_through_plan_bound_wrapper() -> None:
    assert 'record-throughput-human-review-from-ab-plan.ps1' in CONTINUATION
    assert 'record-throughput-human-review-from-ab-plan.ps1' in DOC
    assert 'record-recovery-throughput-human-review.ps1' in DOC
    assert 'candidate-owned' in DOC
    assert 'must not be invoked directly' in DOC
    assert 'continuation-authority.json' in DOC
