from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "continue-throughput-review-from-ab-plan.ps1").read_text(encoding="utf-8")


def test_continuation_requires_exact_pbr_to_throughput_gate_receipt() -> None:
    assert "bodyrig-throughput-pbr-human-review-gate" in SCRIPT
    assert "BodyRig\\ab-baseline-plans\\$BaselineJobId-throughput-$CandidateJobId-pbr-gate.json" in SCRIPT
    assert "candidate_run_plan_sha256" in SCRIPT
    assert "pbr_human_review_authority_sha256" in SCRIPT
    assert "pbr_human_review_sha256" in SCRIPT
    assert "pbr_stable_evidence_fingerprint_sha256" in SCRIPT
    assert "human_visual_authority_recorded -ne $true" in SCRIPT
    assert "PBR-to-throughput sequencing gate receipt crossed the comparison-only authority boundary" in SCRIPT


def test_continuation_replays_checkout_bound_pbr_human_review_authority() -> None:
    assert "bodyrig.pbr_human_review_gate" in SCRIPT
    assert "bodyrig\\pbr_human_review_gate.py" in SCRIPT
    assert "PBR human-review gate validator imported from wrong checkout" in SCRIPT
    assert "--baseline-job-id $BaselineJobId --pbr-run-dir $pbrRunDir" in SCRIPT
    assert "bodyrig-pbr-human-review-gate-context" in SCRIPT
    assert "PBR human-review evidence no longer matches the sequencing receipt" in SCRIPT


def test_continuation_binds_exact_stash_performer_across_pbr_and_both_body_jobs() -> None:
    assert '"stash_performer_id",' in SCRIPT
    assert "$stashPerformerId = [string]$gateReceipt.stash_performer_id" in SCRIPT
    assert "PBR-to-throughput sequencing gate receipt has no exact Stash performer identity." in SCRIPT
    assert "[string]$live.stash_performer_id -ne $stashPerformerId" in SCRIPT
    assert "stash_performer_id = $stashPerformerId" in SCRIPT
    assert "[string]$baselineReceipts.stash_performer_id -ne $stashPerformerId" in SCRIPT
    assert "[string]$candidateReceipts.stash_performer_id -ne $stashPerformerId" in SCRIPT
    assert "PBR sequencing, baseline receipt and candidate receipt do not bind the same exact Stash performer." in SCRIPT
    assert "[string]$baselineReceiptsAfter.stash_performer_id -ne $stashPerformerId" in SCRIPT
    assert "[string]$candidateReceiptsAfter.stash_performer_id -ne $stashPerformerId" in SCRIPT
    assert "source_performer_parity_verified = $true" in SCRIPT


def test_performer_parity_is_proved_before_expensive_machine_evidence() -> None:
    receipts = SCRIPT.index("$baselineReceipts = Invoke-ReceiptProbe")
    performer = SCRIPT.index("PBR sequencing, baseline receipt and candidate receipt do not bind the same exact Stash performer.")
    compare = SCRIPT.index("& $compareScript -BaselineJobId")
    assert receipts < performer < compare


def test_pbr_sequence_gate_runs_before_expensive_machine_evidence() -> None:
    gate = SCRIPT.index("$pbrSequencingGate = Invoke-PbrSequencingGateProbe")
    receipts = SCRIPT.index("$baselineReceipts = Invoke-ReceiptProbe")
    compare = SCRIPT.index("& $compareScript -BaselineJobId")
    assert gate < receipts < compare


def test_pbr_sequence_gate_is_replayed_before_continuation_publication() -> None:
    bundle = SCRIPT.index("& $bundleScript -BaselineJobId")
    receipt_replay = SCRIPT.index("$baselineReceiptsAfter = Invoke-ReceiptProbe")
    gate_replay = SCRIPT.index("$pbrSequencingGateAfter = Invoke-PbrSequencingGateProbe")
    stability = SCRIPT.index("Assert-PbrSequencingGateStable -Before $pbrSequencingGate -After $pbrSequencingGateAfter")
    publish = SCRIPT.index('format = "bodyrig-throughput-plan-bound-review-continuation"')
    assert bundle < receipt_replay < gate_replay < stability < publish


def test_continuation_authority_binds_pbr_sequence_without_crossing_boundary() -> None:
    assert "pbr_to_throughput_sequence_verified = $true" in SCRIPT
    assert "stash_performer_id = $stashPerformerId" in SCRIPT
    assert "pbr_gate_receipt_sha256 = [string]$pbrSequencingGate.gate_receipt_sha256" in SCRIPT
    assert "pbr_human_review_authority_sha256 = [string]$pbrSequencingGate.pbr_human_review_authority_sha256" in SCRIPT
    assert "pbr_human_review_sha256 = [string]$pbrSequencingGate.pbr_human_review_sha256" in SCRIPT
    assert "pbr_stable_evidence_fingerprint_sha256 = [string]$pbrSequencingGate.pbr_stable_evidence_fingerprint_sha256" in SCRIPT
    assert "source_performer_parity_verified = $true" in SCRIPT
    assert "comparison_only = $true" in SCRIPT
    assert "human_visual_authority_required = $true" in SCRIPT
    assert "physical_acceptance_authority = $false" in SCRIPT
    assert "promotion_authority = $false" in SCRIPT
    assert "production_activation = $false" in SCRIPT
