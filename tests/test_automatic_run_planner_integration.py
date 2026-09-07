from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.rig_window_authority_policy as authority


REV = "a" * 40


def run_row(name: str, performer: str, body: str) -> dict:
    return {
        "run_root": name,
        "revision": REV,
        "performer_id": performer,
        "body_id": body,
        "session_report": f"/{name}/session.json",
        "acceptance_dir": f"/{name}/clone-output/acceptance",
        "started_at": "2026-09-07T12:00:00Z",
    }


def candidate(run: dict, *, rank: int = 40) -> dict:
    return {
        "kind": "physical-session",
        "rank": rank,
        "stamp": run["started_at"],
        "preferred": False,
        "session_report": run["session_report"],
        "acceptance_dir": run["acceptance_dir"],
        "state": "ready",
        "gate": "automatic-quest",
        "evidence_revision": run["revision"],
        "performer_id": run["performer_id"],
        "body_id": run["body_id"],
        "automatic_run_root": run["run_root"],
    }


def test_explicit_performer_body_validates_only_matching_one_command_runs(tmp_path: Path, monkeypatch) -> None:
    runs = [run_row("a", "11", "body-a"), run_row("b", "22", "body-b")]
    validated: list[str] = []
    monkeypatch.setattr(authority, "discover_run_authorities", lambda _root: (runs, []))

    def build(run):
        validated.append(run["run_root"])
        return candidate(run)

    monkeypatch.setattr(authority, "candidate_from_run", build)
    candidates, rejected = authority._automatic_run_candidates(
        root=tmp_path, performer_id="22", resolved_performer="", body_id="body-b"
    )
    assert rejected == []
    assert validated == ["b"]
    assert [item["automatic_run_root"] for item in candidates] == ["b"]


def test_resolved_person_performer_scopes_one_command_runs_without_body_guess(tmp_path: Path, monkeypatch) -> None:
    runs = [run_row("a", "11", "body-a"), run_row("b", "22", "body-b")]
    monkeypatch.setattr(authority, "discover_run_authorities", lambda _root: (runs, []))
    monkeypatch.setattr(authority, "candidate_from_run", candidate)
    candidates, _ = authority._automatic_run_candidates(
        root=tmp_path, performer_id="", resolved_performer="11", body_id=""
    )
    assert [item["performer_id"] for item in candidates] == ["11"]


def test_unscoped_reusable_one_command_runs_from_multiple_performers_are_ambiguous(tmp_path: Path, monkeypatch) -> None:
    runs = [run_row("a", "11", "body-a"), run_row("b", "22", "body-b")]
    monkeypatch.setattr(authority, "discover_run_authorities", lambda _root: (runs, []))
    monkeypatch.setattr(authority, "candidate_from_run", candidate)
    with pytest.raises(authority.policy.base.RigWindowPlanError, match="multiple Stash performers"):
        authority._automatic_run_candidates(root=tmp_path, performer_id="", resolved_performer="", body_id="")


def test_nonreusable_partial_run_does_not_create_scope_ambiguity(tmp_path: Path, monkeypatch) -> None:
    runs = [run_row("a", "11", "body-a"), run_row("partial", "22", "body-b")]
    monkeypatch.setattr(authority, "discover_run_authorities", lambda _root: (runs, []))
    monkeypatch.setattr(
        authority,
        "candidate_from_run",
        lambda run: None if run["run_root"] == "partial" else candidate(run),
    )
    candidates, _ = authority._automatic_run_candidates(
        root=tmp_path, performer_id="", resolved_performer="", body_id=""
    )
    assert [item["performer_id"] for item in candidates] == ["11"]


def test_guarded_existing_candidates_deduplicates_same_session_path(tmp_path: Path, monkeypatch) -> None:
    session = tmp_path / "same-session.json"
    existing = candidate(run_row("existing", "11", "body-a"))
    existing["session_report"] = str(session)
    discovered = dict(existing)
    discovered["automatic_run_root"] = "automatic-run"

    monkeypatch.setattr(authority, "_ORIGINAL_EXISTING_CANDIDATES", lambda **_kwargs: ([existing], []))
    monkeypatch.setattr(authority, "_automatic_run_candidates", lambda **_kwargs: ([discovered], []))
    monkeypatch.setattr(
        authority,
        "enforce_existing_authority",
        lambda *, repo_root, candidates, rejected: (candidates, rejected),
    )

    candidates, rejected = authority._guarded_existing_candidates(
        repo_root=tmp_path,
        root=tmp_path,
        rows=[],
        performer_id="11",
        resolved_performer="11",
        body_id="body-a",
    )
    assert rejected == []
    assert len(candidates) == 1
    assert candidates[0]["session_report"] == str(session)
