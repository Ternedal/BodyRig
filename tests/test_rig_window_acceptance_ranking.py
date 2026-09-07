from __future__ import annotations

from bodyrig.acceptance_status import AcceptanceStatus
from bodyrig.rig_window_acceptance import AUTOMATIC_STAGE_PROGRESS, GATE_PROGRESS, progress_rank
from bodyrig.rig_window_plan import rank_acceptance_assessments


def _status(*, state: str = "ready", gate: str) -> AcceptanceStatus:
    return AcceptanceStatus(
        state=state,
        gate=gate,
        acceptance_dir="fixture",
        body_id="body-fixture",
        bodyrig_revision="a" * 40,
        message="fixture",
        next_command="fixture",
    )


def test_physical_gate_progress_order_matches_expensive_chain() -> None:
    assert [GATE_PROGRESS[name] for name in (
        "gate-a",
        "windows-probe",
        "windows-attestation",
        "quest-probe",
        "quest-attestation",
        "release",
    )] == sorted(GATE_PROGRESS.values())


def test_automatic_progress_preserves_real_completed_work_order() -> None:
    assert [AUTOMATIC_STAGE_PROGRESS[name] for name in (
        "windows",
        "quest",
        "quest-quality",
        "release",
        "complete",
    )] == [16, 40, 50, 60, 100]
    assert AUTOMATIC_STAGE_PROGRESS["windows"] > GATE_PROGRESS["gate-a"]
    assert AUTOMATIC_STAGE_PROGRESS["quest"] == GATE_PROGRESS["quest-probe"]
    assert AUTOMATIC_STAGE_PROGRESS["quest-quality"] == GATE_PROGRESS["quest-attestation"]
    assert AUTOMATIC_STAGE_PROGRESS["release"] == GATE_PROGRESS["release"]


def test_complete_acceptance_always_ranks_above_pending_release() -> None:
    assert progress_rank(_status(state="complete", gate="release")) == 100
    assert progress_rank(_status(gate="release")) == 60


def test_blocked_structural_evidence_is_never_ranked_for_reuse() -> None:
    assert progress_rank(_status(state="blocked", gate="quest-attestation")) == 0


def test_furthest_gate_beats_newer_timestamp() -> None:
    newest_early = {
        "acceptance_dir": "new-gate-a",
        "progress_rank": GATE_PROGRESS["gate-a"],
        "stamp": "2099-01-01T00:00:00Z",
    }
    older_late = {
        "acceptance_dir": "old-quest",
        "progress_rank": GATE_PROGRESS["quest-attestation"],
        "stamp": "2026-01-01T00:00:00Z",
    }

    ranked = rank_acceptance_assessments([newest_early, older_late])
    assert [item["acceptance_dir"] for item in ranked] == ["old-quest", "new-gate-a"]


def test_automatic_quality_recovery_beats_newer_windows_only_evidence() -> None:
    newer_windows = {
        "acceptance_dir": "new-windows",
        "progress_rank": AUTOMATIC_STAGE_PROGRESS["quest"],
        "stamp": "2099-01-01T00:00:00Z",
    }
    older_quality_recovery = {
        "acceptance_dir": "old-quest-quality",
        "progress_rank": AUTOMATIC_STAGE_PROGRESS["quest-quality"],
        "stamp": "2026-01-01T00:00:00Z",
    }
    ranked = rank_acceptance_assessments([newer_windows, older_quality_recovery])
    assert [item["acceptance_dir"] for item in ranked] == ["old-quest-quality", "new-windows"]


def test_timestamp_only_breaks_ties_at_same_gate() -> None:
    older = {"acceptance_dir": "older", "progress_rank": 40, "stamp": "2026-01-01T00:00:00Z"}
    newer = {"acceptance_dir": "newer", "progress_rank": 40, "stamp": "2026-09-01T00:00:00Z"}

    ranked = rank_acceptance_assessments([older, newer])
    assert [item["acceptance_dir"] for item in ranked] == ["newer", "older"]
