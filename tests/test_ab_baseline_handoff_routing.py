from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
AB_DOC = (ROOT / "docs" / "AB_BASELINE.md").read_text(encoding="utf-8")


def test_handoff_routes_dual_candidate_baseline_through_plan_bound_wrapper() -> None:
    assert "start-ab-baseline.ps1" in HANDOFF
    assert "#196" in HANDOFF
    assert "#208" in HANDOFF
    assert "shared" in HANDOFF.lower()
    assert "baseline plan" in HANDOFF.lower()
    assert "start-ab-baseline.ps1" in AB_DOC
    assert "canonical operator entrypoint" in AB_DOC


def test_handoff_keeps_generic_revision_bound_launcher_for_non_ab_builds() -> None:
    assert "start-revision-bound-body-build.ps1" in HANDOFF
    assert "ordinary standalone fresh `body-build`" in HANDOFF
    assert "shared dual-candidate baseline-plan authority" in HANDOFF
    assert "merely because it otherwise succeeded" in HANDOFF
