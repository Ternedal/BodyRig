from pathlib import Path


def test_finalizer_requires_sealed_pr40_handoff_before_ab_and_review() -> None:
    text = Path("finalize-pr40-pr41-review.ps1").read_text(encoding="utf-8")
    assert "invoke-pr40-physical-handoff.ps1" in text
    assert "-Mode Verify" in text
    assert "pr40-physical-handoff.json" in text
    assert "candidate_records" in text
    assert "full-reconstruction" in text
    assert "pr41-clean-ab" in text
    assert "lauren-phillips-pr41-ab.mrbody" in text
    assert "compare-fidelity-ab.ps1" in text
    assert "build-fidelity-review-bundle.ps1" in text
    assert "integration-64aa-8a891565\\snapshots" in text
    assert "human face/skin/hair/appearance review remains mandatory" in text
    assert "does not grant production activation" in text
