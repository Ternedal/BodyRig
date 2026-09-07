from __future__ import annotations

from pathlib import Path

import bodyrig.rig_window_plan as planner


HEAD = "a" * 40


def _stub_head(_root: Path) -> str:
    return HEAD


def test_acceptance_ranking_is_progress_first() -> None:
    ranked = planner.rank_acceptance_assessments(
        [
            {"progress_rank": 10, "stamp": "2099-01-01T00:00:00Z", "id": "new-early"},
            {"progress_rank": 50, "stamp": "2026-01-01T00:00:00Z", "id": "old-late"},
        ]
    )
    assert [item["id"] for item in ranked] == ["old-late", "new-early"]


def test_fresh_reconstruction_is_only_final_fallback(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "_head", _stub_head)
    monkeypatch.setattr(planner, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(planner, "_job_rows", lambda _root: [])
    monkeypatch.setattr(planner, "_completed_sessions", lambda _root, revision: [])

    plan = planner.build_plan(
        repo_root=tmp_path,
        performer_id="stash-performer-7",
        body_id="body-seven",
    )

    assert plan["path"] == "fresh-profiled-physical-preflight"
    assert plan["priority"] == 5
    assert plan["expensive_reconstruction_rerun"] is True
    assert plan["fitter_rerun"] is True
    assert "-PerformerId 'stash-performer-7'" in plan["next_command"]
    assert "-BodyId 'body-seven'" in plan["next_command"]


def test_historical_acceptance_is_selected_without_reconstruction(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "_head", _stub_head)
    monkeypatch.setattr(planner, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        planner,
        "_job_rows",
        lambda _root: [
            {
                "job_id": "job-" + "1" * 32,
                "person_id": "person-" + "2" * 32,
                "status": "succeeded",
                "error": "",
                "resume_source_error": "",
                "acceptance_dir": str(tmp_path / "acceptance"),
                "bodyrig_revision": "b" * 40,
                "stamp": "2026-01-01T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(
        planner,
        "_acceptance_assessments",
        lambda _rows: [
            {
                "job_id": "job-" + "1" * 32,
                "person_id": "person-" + "2" * 32,
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
    assert plan["expensive_reconstruction_rerun"] is False
    assert plan["fitter_rerun"] is False
    assert "-Revision '" + "b" * 40 + "' -NoBrowser" in plan["next_command"]


def test_unsafe_historical_acceptance_does_not_block_valid_current_candidate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(planner, "_head", _stub_head)
    monkeypatch.setattr(planner, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(
        planner,
        "_job_rows",
        lambda _root: [
            {
                "job_id": "job-" + "3" * 32,
                "person_id": "person-" + "4" * 32,
                "status": "succeeded",
                "error": "",
                "resume_source_error": "",
                "acceptance_dir": "historical",
                "bodyrig_revision": "b" * 40,
                "stamp": "2026-02-01T00:00:00Z",
            },
            {
                "job_id": "job-" + "5" * 32,
                "person_id": "person-" + "6" * 32,
                "status": "succeeded",
                "error": "",
                "resume_source_error": "",
                "acceptance_dir": "current",
                "bodyrig_revision": HEAD,
                "stamp": "2026-01-01T00:00:00Z",
            },
        ],
    )
    monkeypatch.setattr(
        planner,
        "_acceptance_assessments",
        lambda _rows: [
            {
                "job_id": "job-" + "3" * 32,
                "person_id": "person-" + "4" * 32,
                "acceptance_dir": "historical",
                "stamp": "2026-02-01T00:00:00Z",
                "state": "ready",
                "gate": "quest-attestation",
                "evidence_revision": "b" * 40,
                "progress_rank": 50,
            },
            {
                "job_id": "job-" + "5" * 32,
                "person_id": "person-" + "6" * 32,
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
    assert plan["next_command"] == "current-command"
    assert plan["progress_rank"] == 20
