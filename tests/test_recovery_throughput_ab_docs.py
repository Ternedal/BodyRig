from pathlib import Path


DOC = (Path(__file__).resolve().parents[1] / "docs" / "RECOVERY_THROUGHPUT_AB.md").read_text(encoding="utf-8")


def test_runbook_uses_explicit_revision_bound_machine_and_human_chain() -> None:
    assert "<baseline-bodyrig-revision>" in DOC
    assert "compare-recovery-throughput.ps1" in DOC
    assert "build-recovery-throughput-review-bundle.ps1" in DOC
    assert "record-recovery-throughput-human-review.ps1" in DOC
    assert "eligible-for-human-ab-review" in DOC
    assert "eligible-for-explicit-promotion-review" in DOC


def test_runbook_has_no_historical_branch_or_sha_authority() -> None:
    assert "0b8f61b6f369e0d63ed006d808e316798121f79f" not in DOC
    assert "agent/person-studio-photoreal-20260902" not in DOC
    assert "agent/recovery-throughput-v3-20260903" not in DOC


def test_runbook_never_equates_green_evidence_with_promotion() -> None:
    assert "CI, lower frame count, or faster runtime can never promote it by themselves" in DOC
    assert "promotion_authority = false" in DOC
    assert "production_activation = false" in DOC
    assert "Do not merge or activate the candidate merely because" in DOC
