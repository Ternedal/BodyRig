from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "continue-throughput-review-from-ab-plan.ps1").read_text(encoding="utf-8")


def test_plan_bound_continuation_requires_exact_candidate_run_receipt() -> None:
    assert 'bodyrig-throughput-candidate-run-plan' in SCRIPT
    assert 'BodyRig\\ab-baseline-plans\\$BaselineJobId-throughput-$CandidateJobId.json' in SCRIPT
    assert 'baseline_plan_sha256' in SCRIPT
    assert 'candidate_contract_sha256' in SCRIPT
    assert 'baseline_job_json_sha256' in SCRIPT
    assert '[string]$runPlan.candidate_job_id -ne $CandidateJobId' in SCRIPT
    assert '$runPlan.candidate_workspace_retained -ne $false' in SCRIPT


def test_plan_bound_continuation_revalidates_shared_plan_and_refs() -> None:
    assert 'bodyrig-dual-candidate-ab-baseline-plan' in SCRIPT
    assert 'contracts\\ab-baseline-candidates-v1.json' in SCRIPT
    assert 'Get-FileHash -LiteralPath $contractPath -Algorithm SHA256' in SCRIPT
    assert 'branch --show-current' in SCRIPT
    assert '([string]$branchRaw[0]).Trim() -ne $throughputRef' in SCRIPT
    assert '+refs/heads/main:refs/remotes/origin/main' in SCRIPT
    assert '+refs/heads/${throughputRef}:refs/remotes/origin/${throughputRef}' in SCRIPT
    assert 'origin/main moved after the shared A/B baseline plan was created' in SCRIPT
    assert 'Throughput candidate ref moved after candidate-run authority was created' in SCRIPT


def test_plan_bound_continuation_requires_exact_succeeded_jobs() -> None:
    assert '[string]$baselineJob.status -ne "succeeded"' in SCRIPT
    assert '[string]$candidateJob.status -ne "succeeded"' in SCRIPT
    assert '[string]$baselineJob.job_id -ne $BaselineJobId' in SCRIPT
    assert '[string]$candidateJob.job_id -ne $CandidateJobId' in SCRIPT
    assert '[string]$candidateJob.person_id -ne $personId' in SCRIPT
    assert 'bodyrig-ab-baseline-retention' in SCRIPT
    assert 'Candidate body-build unexpectedly carries baseline-retention authority' in SCRIPT


def test_plan_bound_continuation_revalidates_persisted_body_job_receipts() -> None:
    assert 'bodyrig.body_job_receipt_authority' in SCRIPT
    assert 'bodyrig\\body_job_receipt_authority.py' in SCRIPT
    assert 'bodyrig-succeeded-body-job-receipt-authority' in SCRIPT
    assert '-JobId $BaselineJobId -ExpectedRevision $mainRevision -ExpectedPersonId $personId' in SCRIPT
    assert '-JobId $CandidateJobId -ExpectedRevision $throughputRevision -ExpectedPersonId $personId' in SCRIPT
    assert '[string]$baselineReceipts.job_json_sha256 -ne $baselineJobSha' in SCRIPT
    assert '[string]$candidateReceipts.job_json_sha256 -ne $candidateJobSha' in SCRIPT
    assert 'source_binding_sha256' in SCRIPT
    assert 'body_review_sha256' in SCRIPT
    assert 'source_files_sha256' in SCRIPT


def test_plan_bound_continuation_requires_exact_source_manifest_and_file_hash_parity() -> None:
    assert '[string]$baselineReceipts.source_evidence_kind -ne "stash-physical-source-manifest-v1"' in SCRIPT
    assert '[string]$candidateReceipts.source_evidence_kind -ne "stash-physical-source-manifest-v1"' in SCRIPT
    assert '[string]$baselineReceipts.source_evidence_sha256 -ne [string]$candidateReceipts.source_evidence_sha256' in SCRIPT
    assert '[string]$baselineReceipts.source_files_sha256 -ne [string]$candidateReceipts.source_files_sha256' in SCRIPT
    assert 'same exact Stash physical source manifest and success-time source-file hashes' in SCRIPT
    assert 'source_manifest_parity_verified = $true' in SCRIPT
    assert 'source_file_hashes_parity_verified = $true' in SCRIPT
    assert 'source_evidence_sha256 = $sourceManifestSha' in SCRIPT
    assert 'source_files_sha256 = $sourceFilesSha' in SCRIPT


def test_plan_bound_continuation_runs_machine_gate_before_bundle() -> None:
    receipt_probe = SCRIPT.index('$baselineReceipts = Invoke-ReceiptProbe')
    compare = SCRIPT.index('& $compareScript -BaselineJobId')
    machine_pass = SCRIPT.index('machine_evidence_pass -ne $true')
    bundle = SCRIPT.index('& $bundleScript -BaselineJobId')
    replay = SCRIPT.index('$baselineReceiptsAfter = Invoke-ReceiptProbe')
    publish = SCRIPT.index('format = "bodyrig-throughput-plan-bound-review-continuation"')
    assert receipt_probe < compare < machine_pass < bundle < replay < publish
    assert '[string]$machine.baseline_job_id -ne $BaselineJobId' in SCRIPT
    assert '[string]$machine.candidate_job_id -ne $CandidateJobId' in SCRIPT
    assert '[string]$bundle.baseline_job_id -ne $BaselineJobId' in SCRIPT
    assert '[string]$bundle.candidate_job_id -ne $CandidateJobId' in SCRIPT


def test_plan_bound_continuation_replays_receipt_authority_before_publication() -> None:
    assert 'Assert-ReceiptProbeStable -Before $baselineReceipts -After $baselineReceiptsAfter' in SCRIPT
    assert 'Assert-ReceiptProbeStable -Before $candidateReceipts -After $candidateReceiptsAfter' in SCRIPT
    assert 'Shared Stash physical source authority changed while generating throughput review evidence.' in SCRIPT
    assert '[string]$baselineReceiptsAfter.source_files_sha256 -ne $sourceFilesSha' in SCRIPT
    assert '[string]$candidateReceiptsAfter.source_files_sha256 -ne $sourceFilesSha' in SCRIPT
    for field in (
        'baseline_job_json_sha256',
        'candidate_job_json_sha256',
        'baseline_source_binding_sha256',
        'candidate_source_binding_sha256',
        'baseline_body_review_sha256',
        'candidate_body_review_sha256',
        'baseline_body_revision',
        'candidate_body_revision',
        'source_files_sha256',
    ):
        assert field in SCRIPT


def test_plan_bound_continuation_is_create_only_and_never_records_human_pass() -> None:
    assert 'Refusing to overwrite existing plan-bound throughput review output' in SCRIPT
    assert 'Move-Item -LiteralPath $tempRoot -Destination $finalRoot' in SCRIPT
    assert 'record-recovery-throughput-human-review.ps1' in SCRIPT
    assert '& $humanScript' not in SCRIPT
    assert 'READY FOR EXPLICIT HUMAN REVIEW' in SCRIPT
    assert 'comparison_only = $true' in SCRIPT
    assert 'human_visual_authority_required = $true' in SCRIPT
    assert 'physical_acceptance_authority = $false' in SCRIPT
    assert 'promotion_authority = $false' in SCRIPT
    assert 'production_activation = $false' in SCRIPT
