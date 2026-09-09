from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDOFF = (ROOT / "HANDOFF.md").read_text(encoding="utf-8")
AB_DOC = (ROOT / "docs" / "AB_BASELINE.md").read_text(encoding="utf-8")


def test_handoff_routes_dual_candidate_baseline_through_plan_bound_wrapper() -> None:
    assert "start-ab-baseline.ps1" in HANDOFF
    assert "#258" in HANDOFF
    assert "#208" in HANDOFF
    assert "shared" in HANDOFF.lower()
    assert "baseline plan" in HANDOFF.lower()
    assert "start-ab-baseline.ps1" in AB_DOC
    assert "canonical operator entrypoint" in AB_DOC


def test_handoff_classifies_pbr_v3_current_and_v2_superseded() -> None:
    assert "#258 — ACTIVE/DRAFT CURRENT-MAIN CANDIDATE" in HANDOFF
    assert "#196 — SUPERSEDED PBR-V2 CANDIDATE" in HANDOFF
    assert "#196 — ACTIVE/DRAFT CURRENT-MAIN CANDIDATE" not in HANDOFF


def test_handoff_keeps_generic_revision_bound_launcher_for_non_ab_builds() -> None:
    assert "start-revision-bound-body-build.ps1" in HANDOFF
    assert "ordinary standalone fresh `body-build`" in HANDOFF
    assert "shared dual-candidate baseline-plan authority" in HANDOFF
    assert "merely because it otherwise succeeded" in HANDOFF


def test_handoff_preserves_shared_baseline_context_through_terminal_monitoring() -> None:
    assert ".\\watch-body-build.ps1 -JobId '<baseline-job>'" in HANDOFF
    assert ".\\run-pbr-ab-from-body-job-plan-bound.ps1 -BaselineJobId '<baseline-job>'" in HANDOFF
    assert "watcher remains read-only and grants no A/B, physical, promotion or production authority" in HANDOFF
    assert "downstream plan-bound wrapper still revalidates full authority" in HANDOFF
    assert "A/B BASELINE CONTINUATION BLOCKED" in HANDOFF


def test_handoff_and_runbook_require_service_bound_fail_fast_physical_readiness() -> None:
    for text in (HANDOFF, AB_DOC):
        assert "service-bound" in text
        assert "reference-renderer" in text
        assert "ffmpeg-one-frame-v1" in text
        assert "no physical" in text.lower()
    assert "same service checkout/environment/Python/PATH" in HANDOFF
    assert "does not create session/readiness evidence" in AB_DOC
