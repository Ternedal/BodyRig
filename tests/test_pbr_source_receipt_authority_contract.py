from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "bodyrig" / "pbr_ab_body_job_source.py").read_text(encoding="utf-8")
RUNNER = (ROOT / "run-pbr-ab-from-body-job-internal.ps1").read_text(encoding="utf-8")
REVIEW = (ROOT / "record-pbr-ab-human-review-from-plan.ps1").read_text(encoding="utf-8")


def test_pbr_source_validator_revalidates_persisted_person_receipts() -> None:
    assert "read_binding" in SOURCE
    assert "read_review" in SOURCE
    assert 're.compile(r"^body-r[0-9]{4}$")' in SOURCE
    assert '"source_binding_sha256": actual_source_binding_sha' in SOURCE
    assert '"body_review_sha256": actual_review_sha' in SOURCE
    assert "source binding receipt changed after body job success" in SOURCE
    assert "body fidelity review receipt changed after body job success" in SOURCE


def test_pbr_run_source_authority_carries_verified_receipt_hashes() -> None:
    assert '"source_binding_sha256"' in RUNNER
    assert '"body_review_sha256"' in RUNNER
    assert "source_binding_sha256 = [string]$sourceBefore.source_binding_sha256" in RUNNER
    assert "body_review_sha256 = [string]$sourceBefore.body_review_sha256" in RUNNER
    assert '"body_revision"' in RUNNER
    assert '"canonical_body_id"' in RUNNER


def test_plan_bound_human_review_replays_persisted_source_authority() -> None:
    assert "function Invoke-SourceProbe" in REVIEW
    assert "function Assert-SourceProbeMatchesAuthority" in REVIEW
    assert "source_binding_sha256" in REVIEW
    assert "body_review_sha256" in REVIEW
    assert "$sourceBeforeReview = Invoke-SourceProbe" in REVIEW
    assert "$sourceAfterReview = Invoke-SourceProbe" in REVIEW
    assert "$sourceBeforeTerminal = Invoke-SourceProbe" in REVIEW
    assert "Persisted PBR source evidence changed during human review; removed non-authoritative receipt" in REVIEW
