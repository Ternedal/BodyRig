from pathlib import Path

from bodyrig.acceptance_status import AcceptanceStatus
import bodyrig.rig_window_policy as policy


HEAD = "a" * 40
OLD = "b" * 40


def _rework_candidate() -> dict[str, object]:
    return {
        "kind": "human-fidelity-rework",
        "rank": policy.HUMAN_FIDELITY_REWORK_RANK,
        "stamp": "2026-09-07T20:00:00Z",
        "preferred": False,
        "session_report": r"C:\\evidence\\session.json",
        "state": "blocked",
        "gate": "windows-rejected",
        "acceptance_dir": r"C:\\evidence\\acceptance",
        "evidence_revision": OLD,
        "performer_id": "42",
        "body_id": "lauren-phillips-test-01",
    }


def test_windows_human_rejection_is_retained_as_low_priority_rework(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        policy,
        "_scope_sessions",
        lambda *_args, **_kwargs: [
            {
                "path": str(tmp_path / "session.json"),
                "stamp": "2026-09-07T20:00:00Z",
                "performer_id": "42",
                "body_id": "lauren-phillips-test-01",
                "revision": OLD,
            }
        ],
    )
    monkeypatch.setattr(
        policy,
        "_session_status",
        lambda _path: AcceptanceStatus(
            state="blocked",
            gate="windows-rejected",
            acceptance_dir=str(tmp_path / "acceptance"),
            body_id="bodyid-1234567890abcdef12345678",
            bodyrig_revision=OLD,
            message="Human renderer fidelity rejection is authoritative.",
            next_command=None,
        ),
    )

    candidates, rejected = policy._existing_candidates(
        repo_root=tmp_path,
        root=tmp_path,
        rows=[],
        performer_id="42",
        resolved_performer="42",
        body_id="lauren-phillips-test-01",
    )

    assert rejected == []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["kind"] == "human-fidelity-rework"
    assert candidate["rank"] == 1
    assert candidate["gate"] == "windows-rejected"
    assert candidate["evidence_revision"] == OLD


def test_positive_progress_still_outranks_human_rework() -> None:
    positive = {
        "kind": "physical-session",
        "rank": policy.SESSION_RANK,
        "stamp": "2026-09-01T00:00:00Z",
        "preferred": False,
    }
    ranked = policy.rank_physical_candidates([_rework_candidate(), positive])
    assert ranked[0]["kind"] == "physical-session"
    assert ranked[-1]["kind"] == "human-fidelity-rework"


def test_rejected_fidelity_routes_to_current_profiled_convergence_with_retention(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(policy.base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(policy.base, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(policy.base, "_job_rows", lambda _root: [])
    monkeypatch.setattr(policy.base, "resolve_person_scope", lambda **_kwargs: ("", "42"))
    monkeypatch.setattr(policy.base, "_scope_rows", lambda _rows, **_kwargs: [])
    monkeypatch.setattr(policy, "_existing_candidates", lambda **_kwargs: ([_rework_candidate()], []))
    monkeypatch.setattr(policy, "_rescue_candidates", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(policy, "_interrupted_candidates", lambda *_args, **_kwargs: ([], []))

    plan = policy.build_plan(
        repo_root=tmp_path,
        performer_id="42",
        body_id="lauren-phillips-test-01",
    )

    assert plan["path"] == "human-fidelity-rework"
    assert plan["progress_rank"] == 1
    assert plan["bodyrig_revision"] == HEAD
    assert plan["evidence_revision"] == OLD
    assert plan["gate"] == "windows-rejected"
    assert plan["expensive_reconstruction_rerun"] is True
    assert plan["fitter_rerun"] is True
    command = str(plan["next_command"])
    assert "run-profiled-fidelity-convergence.ps1" in command
    assert "-PerformerId '42'" in command
    assert "-BodyId 'lauren-phillips-test-01'" in command
    assert "-KeepPrivateWorkspaces" in command
    assert "update-windows.ps1" not in command
    assert OLD not in command
