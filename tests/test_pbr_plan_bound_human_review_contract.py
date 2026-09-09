from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "record-pbr-ab-human-review-from-plan.ps1").read_text(encoding="utf-8")


def test_plan_bound_pbr_human_review_requires_shared_plan_and_run_receipts() -> None:
    assert 'bodyrig-dual-candidate-ab-baseline-plan' in SCRIPT
    assert 'BodyRig\\ab-baseline-plans\\$BaselineJobId.json' in SCRIPT
    assert 'contracts\\ab-baseline-candidates-v1.json' in SCRIPT
    assert 'body-job-source-authority.json' in SCRIPT
    assert 'body-job-plan-authority.json' in SCRIPT
    assert 'bodyrig-pbr-ab-body-job-source-authority' in SCRIPT
    assert 'bodyrig-pbr-ab-body-job-plan-authority' in SCRIPT
    assert 'run_authority_sha256' in SCRIPT
    assert 'source_authority_sha256' in SCRIPT


def test_plan_bound_pbr_human_review_revalidates_exact_main_and_candidate_refs() -> None:
    assert 'Plan-bound PBR human review must be recorded from branch main.' in SCRIPT
    assert 'BodyRig HEAD does not match the shared A/B baseline plan revision.' in SCRIPT
    assert '+refs/heads/main:refs/remotes/origin/main' in SCRIPT
    assert '+refs/heads/${PbrRef}:refs/remotes/origin/${PbrRef}' in SCRIPT
    assert 'origin/main moved after the shared A/B baseline plan was created.' in SCRIPT
    assert 'PBR candidate ref moved after the shared A/B baseline plan was created.' in SCRIPT
    assert 'Candidate byte contract bytes differ from the shared A/B baseline plan.' in SCRIPT


def test_plan_bound_pbr_human_review_delegates_actual_visual_receipt_to_canonical_recorder() -> None:
    assert 'record-fidelity-ab-review.ps1' in SCRIPT
    assert 'AbEvidence = $machineAbPath' in SCRIPT
    assert 'LeftRenderDir = $leftRenderDir' in SCRIPT
    assert 'RightRenderDir = $rightRenderDir' in SCRIPT
    assert 'ConfirmVisualReview = $true' in SCRIPT
    assert '& $recorder @recordParams' in SCRIPT
    assert 'bodyrig-fidelity-ab-human-review' in SCRIPT
    assert 'review.left.builder_revision' in SCRIPT
    assert 'review.right.builder_revision' in SCRIPT


def test_plan_bound_pbr_human_review_is_create_only_and_fail_closed() -> None:
    assert 'Human A/B review already exists' in SCRIPT
    assert 'Plan-bound PBR human-review authority already exists' in SCRIPT
    assert 'removed non-authoritative receipt' in SCRIPT
    assert 'bodyrig-pbr-plan-bound-human-review-authority' in SCRIPT
    assert 'human_review_sha256' in SCRIPT
    assert 'Remove-Item -LiteralPath $humanAuthorityPath -Force' in SCRIPT
    assert 'Remove-Item -LiteralPath $humanReviewPath -Force' in SCRIPT
    assert 'comparison_only = $true' in SCRIPT
    assert 'human_visual_authority_recorded = $true' in SCRIPT
    assert 'physical_acceptance_authority = $false' in SCRIPT
    assert 'promotion_authority = $false' in SCRIPT
    assert 'production_activation = $false' in SCRIPT


def test_plan_bound_pbr_human_review_routes_to_throughput_without_auto_start() -> None:
    assert 'Next canonical shared-plan step:' in SCRIPT
    assert '.\\start-throughput-candidate-from-ab-plan.ps1 -BaselineJobId' in SCRIPT
    assert 'Routing only: the throughput command is not executed automatically' in SCRIPT
    assert '& .\\start-throughput-candidate-from-ab-plan.ps1' not in SCRIPT
    assert '& $throughput' not in SCRIPT
