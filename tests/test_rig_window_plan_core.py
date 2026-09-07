from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.rig_window_plan as planner


HEAD = "a" * 40
PERSON_A = "person-" + "1" * 32
PERSON_B = "person-" + "2" * 32


def _stub_head(_root: Path) -> str:
    return HEAD


def _profile(person_id: str, performer_id: str) -> dict:
    return {
        "person_id": person_id,
        "source": {
            "kind": "stash-performer",
            "performer_id": performer_id,
            "performer_name": performer_id,
            "disambiguation": "",
        },
    }


def _row(*, person_id: str, job_digit: str, acceptance_dir: str = "", revision: str = HEAD) -> dict:
    return {
        "job_id": "job-" + job_digit * 32,
        "person_id": person_id,
        "status": "succeeded",
        "error": "",
        "resume_source_error": "",
        "acceptance_dir": acceptance_dir,
        "bodyrig_revision": revision,
        "stamp": "2026-01-01T00:00:00Z",
    }


def test_acceptance_ranking_is_progress_first() -> None:
    ranked = planner.rank_acceptance_assessments(
        [
            {"progress_rank": 10, "stamp": "2099-01-01T00:00:00Z", "id": "new-early"},
            {"progress_rank": 50, "stamp": "2026-01-01T00:00:00Z", "id": "old-late"},
        ]
    )
    assert [item["id"] for item in ranked] == ["old-late", "new-early"]


def test_unscoped_multiple_people_fail_closed(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "_head", _stub_head)
    monkeypatch.setattr(planner, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(planner, "_profiles", lambda _root: [])
    monkeypatch.setattr(
        planner,
        "_job_rows",
        lambda _root: [
            _row(person_id=PERSON_A, job_digit="1"),
            _row(person_id=PERSON_B, job_digit="2"),
        ],
    )

    with pytest.raises(planner.RigWindowPlanError, match="multiple BodyRig Persons|multiple BodyRig Persons" if False else "multiple BodyRig Persons"):
        planner.build_plan(repo_root=tmp_path)


def test_performer_scope_resolves_unique_person_and_drops_other_jobs(tmp_path: Path, monkeypatch) -> None:
    rows = [
        _row(person_id=PERSON_A, job_digit="1"),
        _row(person_id=PERSON_B, job_digit="2"),
    ]
    monkeypatch.setattr(planner, "_profiles", lambda _root: [_profile(PERSON_A, "performer-a"), _profile(PERSON_B, "performer-b")])

    person_id, performer_id = planner.resolve_person_scope(
        root=tmp_path,
        rows=rows,
        performer_id="performer-b",
    )
    scoped = planner._scope_rows(rows, person_id=person_id, performer_requested=True)

    assert person_id == PERSON_B
    assert performer_id == "performer-b"
    assert [row["person_id"] for row in scoped] == [PERSON_B]


def test_duplicate_person_profiles_for_one_performer_require_explicit_person(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "_profiles", lambda _root: [_profile(PERSON_A, "same"), _profile(PERSON_B, "same")])

    with pytest.raises(planner.RigWindowPlanError, match="pass -PersonId explicitly"):
        planner.resolve_person_scope(root=tmp_path, rows=[], performer_id="same")


def test_explicit_person_must_match_requested_performer(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "_profiles", lambda _root: [_profile(PERSON_A, "performer-a")])

    with pytest.raises(planner.RigWindowPlanError, match="not performer-b"):
        planner.resolve_person_scope(
            root=tmp_path,
            rows=[],
            person_id=PERSON_A,
            performer_id="performer-b",
        )


def test_fresh_reconstruction_is_only_final_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "_head", _stub_head)
    monkeypatch.setattr(planner, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(planner, "_profiles", lambda _root: [])
    monkeypatch.setattr(planner, "_job_rows", lambda _root: [])
    monkeypatch.setattr(planner, "_completed_sessions", lambda _root, **_kwargs: [])

    plan = planner.build_plan(
        repo_root=tmp_path,
        performer_id="stash-performer-7",
        body_id="body-seven",
    )

    assert plan["path"] == "fresh-profiled-physical-preflight"
    assert plan["priority"] == 5
    assert plan["expensive_reconstruction_rerun"] is True
    assert plan["fitter_rerun"] is True
    assert plan["scope"]["performer_id"] == "stash-performer-7"
    assert "-PerformerId 'stash-performer-7'" in plan["next_command"]
    assert "-BodyId 'body-seven'" in plan["next_command"]


def test_historical_acceptance_is_selected_without_reconstruction(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "_head", _stub_head)
    monkeypatch.setattr(planner, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(planner, "_profiles", lambda _root: [])
    monkeypatch.setattr(
        planner,
        "_job_rows",
        lambda _root: [
            _row(
                person_id=PERSON_A,
                job_digit="3",
                acceptance_dir=str(tmp_path / "acceptance"),
                revision="b" * 40,
            )
        ],
    )
    monkeypatch.setattr(
        planner,
        "_acceptance_assessments",
        lambda _rows: [
            {
                "job_id": "job-" + "3" * 32,
                "person_id": PERSON_A,
                "acceptance_dir": str(tmp_path / "acceptance"),
                "stamp": "2026-01-01T00:00:00Z",
                "state": "ready",
                "gate": "quest-probe",
                "evidence_revision": "b" * 40,
                "progress_rank": 40,
            }
        ],
    )
    monkeypatch.setattr(planner, "_historical_revision_is_safe", lambda _root, _revision: True)

    plan = planner.build_plan(repo_root=tmp_path)

    assert plan["path"] == "historical-acceptance-checkout"
    assert plan["scope"]["person_id"] == PERSON_A
    assert plan["expensive_reconstruction_rerun"] is False
    assert plan["fitter_rerun"] is False
    assert "-Revision '" + "b" * 40 + "' -NoBrowser" in plan["next_command"]


def test_unsafe_historical_acceptance_does_not_block_valid_current_candidate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "_head", _stub_head)
    monkeypatch.setattr(planner, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(planner, "_profiles", lambda _root: [])
    monkeypatch.setattr(
        planner,
        "_job_rows",
        lambda _root: [
            _row(person_id=PERSON_A, job_digit="4", acceptance_dir="historical", revision="b" * 40),
            _row(person_id=PERSON_A, job_digit="5", acceptance_dir="current", revision=HEAD),
        ],
    )
    monkeypatch.setattr(
        planner,
        "_acceptance_assessments",
        lambda _rows: [
            {
                "job_id": "job-" + "4" * 32,
                "person_id": PERSON_A,
                "acceptance_dir": "historical",
                "stamp": "2026-02-01T00:00:00Z",
                "state": "ready",
                "gate": "quest-attestation",
                "evidence_revision": "b" * 40,
                "progress_rank": 50,
            },
            {
                "job_id": "job-" + "5" * 32,
                "person_id": PERSON_A,
                "acceptance_dir": "current",
                "stamp": "2026-01-01T00:00:00Z",
                "state": "ready",
                "gate": "windows-probe",
                "evidence_revision": HEAD,
                "progress_rank": 20,
            },
        ],
    )
    monkeypatch.setattr(planner, "_historical_revision_is_safe", lambda _root, _revision: False)

    class Status:
        state = "ready"
        gate = "windows-probe"
        next_command = "current-command"

    monkeypatch.setattr(planner, "_current_acceptance_status", lambda _path, _root: Status())

    plan = planner.build_plan(repo_root=tmp_path)

    assert plan["path"] == "existing-gate-a-acceptance"
    assert plan["scope"]["person_id"] == PERSON_A
    assert plan["next_command"] == "current-command"
    assert plan["progress_rank"] == 20


def test_standalone_session_scope_requires_exact_performer_and_body(tmp_path: Path, monkeypatch) -> None:
    sessions = [
        {"path": "a", "stamp": "2", "performer_id": "p1", "body_id": "b1"},
        {"path": "b", "stamp": "1", "performer_id": "p2", "body_id": "b2"},
    ]
    monkeypatch.setattr(planner, "_completed_sessions", lambda _root, **_kwargs: sessions)

    # The helper delegates exact filtering to _completed_sessions in production;
    # use a faithful filtering stub to assert the requested authority is passed.
    captured: dict[str, str] = {}

    def filtered(_root: Path, **kwargs):
        captured.update({key: str(value) for key, value in kwargs.items()})
        return [sessions[1]]

    monkeypatch.setattr(planner, "_completed_sessions", filtered)
    selected = planner._scoped_completed_sessions(
        tmp_path,
        revision=HEAD,
        explicit_performer_id="p2",
        resolved_performer_id="p2",
        body_id="b2",
    )

    assert selected == [sessions[1]]
    assert captured["performer_id"] == "p2"
    assert captured["body_id"] == "b2"
