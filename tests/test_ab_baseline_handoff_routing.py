from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
AB_DOC = (ROOT / "docs" / "AB_BASELINE.md").read_text(encoding="utf-8")


def test_handoff_routes_new_work_away_from_completed_ab_v1() -> None:
    assert "completed, promoted and archived" in HANDOFF
    assert "not current new-work operator routing" in HANDOFF
    assert "new versioned candidate contract/lifecycle" in HANDOFF
    assert "Historical shared physical A/B baseline v1" in AB_DOC
    assert "Do not execute this v1 procedure" in AB_DOC


def test_handoff_classifies_reviewed_candidates_as_promoted_historical() -> None:
    assert "#258 — PROMOTED/HISTORICAL PBR-V3 CANDIDATE" in HANDOFF
    assert "#208 — PROMOTED/HISTORICAL THROUGHPUT-V3 CANDIDATE" in HANDOFF
    assert "#258 — ACTIVE/DRAFT CURRENT-MAIN CANDIDATE" not in HANDOFF
    assert "#208 — ACTIVE/DRAFT CURRENT-MAIN CANDIDATE" not in HANDOFF
    assert "#196 — SUPERSEDED PBR-V2 CANDIDATE" in HANDOFF


def test_handoff_keeps_generic_revision_bound_launcher_for_new_non_ab_builds() -> None:
    assert "start-revision-bound-body-build.ps1" in HANDOFF
    assert "ordinary standalone fresh `body-build`" in HANDOFF
    assert "Any future candidate comparison must introduce a new versioned candidate contract/lifecycle first" in HANDOFF


def test_historical_ab_docs_preserve_evidence_interpretation_without_reactivation() -> None:
    assert "start-ab-baseline.ps1" in AB_DOC
    assert "completed-promoted" in AB_DOC
    assert "historical evidence" in AB_DOC.lower()
    assert "must not mutate or reactivate this historical authority" in AB_DOC
