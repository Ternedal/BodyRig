from pathlib import Path

import pytest

import bodyrig.rig_window_component_authority as component


HEAD = "a" * 40
OLD = "b" * 40
PERSON = "person-" + "1" * 32
JOB_A = "job-" + "2" * 32
JOB_B = "job-" + "3" * 32
BODY_A = "lauren-phillips-test-02"
BODY_B = "lauren-other-body"


def _install(tmp_path: Path, monkeypatch, rows: list[dict[str, str]], bodies: dict[str, str]) -> None:
    base = component.authority.policy.base
    for row in rows:
        acceptance = Path(row["acceptance_dir"])
        acceptance.mkdir(parents=True)
        (acceptance / "bodyrig-acceptance.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(base, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(base, "_job_rows", lambda _root: rows)
    monkeypatch.setattr(base, "resolve_person_scope", lambda **_kwargs: (PERSON, "42"))
    monkeypatch.setattr(base, "_historical_revision_is_safe", lambda _root, revision: revision == OLD)
    monkeypatch.setattr(component.authority.policy, "_scope_sessions", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(component.authority, "_automatic_run_candidates", lambda **_kwargs: ([], []))
    monkeypatch.setattr(component, "list_recent_previews", lambda **_kwargs: [])
    monkeypatch.setattr(component, "_validated_failed_checks", lambda _acceptance: frozenset({"hair_appearance"}))

    def inspect(path: Path) -> dict[str, object]:
        job_id = Path(path).parent.name
        return {
            "state": "blocked",
            "gate": "windows-rejected",
            "body_id": bodies[job_id],
            "bodyrig_revision": OLD,
            "progress_rank": 0,
        }

    monkeypatch.setattr(base, "inspect_for_rig_window", inspect)


def _row(tmp_path: Path, job_id: str, stamp: str) -> dict[str, str]:
    return {
        "job_id": job_id,
        "person_id": PERSON,
        "status": "succeeded",
        "error": "",
        "resume_source_error": "",
        "acceptance_dir": str(tmp_path / "ui-jobs" / job_id / "acceptance"),
        "bodyrig_revision": OLD,
        "stamp": stamp,
    }


def test_unscoped_planner_recovers_exact_body_id_from_rejected_acceptance(tmp_path: Path, monkeypatch) -> None:
    rows = [_row(tmp_path, JOB_A, "2026-09-13T07:00:00Z")]
    _install(tmp_path, monkeypatch, rows, {JOB_A: BODY_A})

    plan = component.build_plan(repo_root=tmp_path)

    assert plan["path"] == "high-fidelity-component-rework"
    assert plan["scope"]["person_id"] == PERSON
    assert plan["scope"]["performer_id"] == "42"
    assert plan["scope"]["body_id"] == BODY_A
    assert plan["body_job_id"] == JOB_A
    assert "start-high-fidelity-preview-from-body-job.ps1" in str(plan["next_command"])


def test_unscoped_planner_fails_closed_on_multiple_rejected_body_ids(tmp_path: Path, monkeypatch) -> None:
    rows = [
        _row(tmp_path, JOB_A, "2026-09-13T07:00:00Z"),
        _row(tmp_path, JOB_B, "2026-09-13T08:00:00Z"),
    ]
    _install(tmp_path, monkeypatch, rows, {JOB_A: BODY_A, JOB_B: BODY_B})

    with pytest.raises(component.authority.policy.base.RigWindowPlanError, match="multiple BodyIds"):
        component.build_plan(repo_root=tmp_path)


def test_preferred_job_disambiguates_rejected_body_id_without_guessing(tmp_path: Path, monkeypatch) -> None:
    rows = [
        _row(tmp_path, JOB_A, "2026-09-13T07:00:00Z"),
        _row(tmp_path, JOB_B, "2026-09-13T08:00:00Z"),
    ]
    _install(tmp_path, monkeypatch, rows, {JOB_A: BODY_A, JOB_B: BODY_B})

    plan = component.build_plan(repo_root=tmp_path, preferred_job_id=JOB_A)

    assert plan["scope"]["body_id"] == BODY_A
    assert plan["body_job_id"] == JOB_A
    assert f"-BodyJobId '{JOB_A}'" in str(plan["next_command"])
