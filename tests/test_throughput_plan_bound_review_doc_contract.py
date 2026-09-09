from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = (ROOT / "docs" / "THROUGHPUT_PLAN_BOUND_REVIEW.md").read_text(encoding="utf-8")


def test_runbook_routes_long_running_candidate_through_plan_bound_watcher() -> None:
    assert "## Monitor the long-running candidate" in DOC
    assert ".\\watch-throughput-candidate-from-ab-plan.ps1" in DOC
    assert "-BaselineJobId '<baseline-job>'" in DOC
    assert "-CandidateJobId '<candidate-job>'" in DOC
    assert "THROUGHPUT CANDIDATE CONTINUATION BLOCKED" in DOC
    assert "The watcher is deliberately advisory" in DOC
    assert ".\\continue-throughput-review-from-ab-plan.ps1" in DOC


def test_runbook_preserves_performer_and_terminal_authority_boundaries() -> None:
    assert "PBR-reviewed performer == baseline succeeded-job performer == candidate succeeded-job performer" in DOC
    assert "continuation-authority SHA" in DOC
    assert "verified Stash performer" in DOC
    assert "does not grant physical acceptance, promotion authority or production activation" in DOC
    assert "must not be invoked directly" in DOC
