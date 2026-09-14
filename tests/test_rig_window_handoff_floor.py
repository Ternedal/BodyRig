from __future__ import annotations

from pathlib import Path

import bodyrig.rig_window_handoff_floor as floor


HEAD = "a" * 40
HISTORICAL = "b" * 40
CURRENT_FLOOR = "fe04ab113c3c57ed1f3d502242fc0e51b0629b04"
CURRENT_FLOOR_CONTRACT = "drawable hair/eye + complete component visibility + adaptive short-hair-v2 contract"


def _candidate(*, revision: str = HISTORICAL, kind: str = "physical-session") -> dict:
    return {
        "kind": kind,
        "gate": "windows-probe",
        "rank": 20,
        "stamp": "2026-09-06T09:21:54Z",
        "preferred": False,
        "session_report": r"C:\BodyRig\historical-session.json",
        "acceptance_dir": r"C:\BodyRig\historical-acceptance",
        "state": "ready",
        "evidence_revision": revision,
        "performer_id": "42",
        "body_id": "lauren-phillips-test-01",
    }


def test_drawable_short_hair_merge_is_the_current_physical_handoff_floor() -> None:
    assert floor.MINIMUM_PHYSICAL_HANDOFF_REVISION == CURRENT_FLOOR


def test_historical_physical_session_before_floor_is_rejected_before_ranking(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        floor,
        "_ORIGINAL_ENFORCE_EXISTING_AUTHORITY",
        lambda **kwargs: (list(kwargs["candidates"]), list(kwargs["rejected"])),
    )
    monkeypatch.setattr(floor.component.authority.policy.base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(floor, "_revision_meets_current_handoff_floor", lambda _root, _revision: False)

    kept, rejected = floor.enforce_existing_authority(
        repo_root=tmp_path,
        candidates=[_candidate()],
        rejected=[],
    )

    assert kept == []
    assert len(rejected) == 1
    assert rejected[0]["evidence"] == r"C:\BodyRig\historical-acceptance"
    assert HISTORICAL in rejected[0]["reason"]
    assert floor.MINIMUM_PHYSICAL_HANDOFF_REVISION in rejected[0]["reason"]
    assert CURRENT_FLOOR_CONTRACT in rejected[0]["reason"]


def test_historical_ui_acceptance_at_or_after_floor_remains_eligible(tmp_path: Path, monkeypatch) -> None:
    candidate = _candidate(kind="ui-acceptance")
    monkeypatch.setattr(
        floor,
        "_ORIGINAL_ENFORCE_EXISTING_AUTHORITY",
        lambda **kwargs: (list(kwargs["candidates"]), list(kwargs["rejected"])),
    )
    monkeypatch.setattr(floor.component.authority.policy.base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(floor, "_revision_meets_current_handoff_floor", lambda _root, _revision: True)

    kept, rejected = floor.enforce_existing_authority(
        repo_root=tmp_path,
        candidates=[candidate],
        rejected=[],
    )

    assert rejected == []
    assert kept == [candidate]


def test_current_revision_physical_evidence_does_not_need_historical_floor_probe(tmp_path: Path, monkeypatch) -> None:
    candidate = _candidate(revision=HEAD)
    monkeypatch.setattr(
        floor,
        "_ORIGINAL_ENFORCE_EXISTING_AUTHORITY",
        lambda **kwargs: (list(kwargs["candidates"]), list(kwargs["rejected"])),
    )
    monkeypatch.setattr(floor.component.authority.policy.base, "_head", lambda _root: HEAD)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("current evidence must not be subjected to historical handoff-floor routing")

    monkeypatch.setattr(floor, "_revision_meets_current_handoff_floor", unexpected)
    kept, rejected = floor.enforce_existing_authority(
        repo_root=tmp_path,
        candidates=[candidate],
        rejected=[],
    )

    assert rejected == []
    assert kept == [candidate]


def test_pre_floor_gate_a_rescue_is_rejected_before_progress_ranking(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(floor.component.authority.policy.base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(floor, "_revision_meets_current_handoff_floor", lambda _root, _revision: False)
    candidate = {
        "kind": "gate-a-rescue",
        "job_id": "job-" + "1" * 32,
        "evidence_revision": HISTORICAL,
    }

    kept, rejected = floor._filter_rescue_candidates(tmp_path, [candidate], [])

    assert kept == []
    assert rejected[0]["job_id"] == candidate["job_id"]
    assert CURRENT_FLOOR_CONTRACT in rejected[0]["reason"]


def test_interrupted_recovery_requires_proven_floor_compatible_job_revision(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(floor.component.authority.policy.base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(floor, "_revision_meets_current_handoff_floor", lambda _root, _revision: False)
    job_id = "job-" + "2" * 32
    rows = [{"job_id": job_id, "bodyrig_revision": HISTORICAL}]
    candidate = {"kind": "interrupted-body-recovery", "job_id": job_id}

    kept, rejected = floor._filter_interrupted_candidates(tmp_path, rows, [candidate], [])

    assert kept == []
    assert rejected[0]["job_id"] == job_id
    assert HISTORICAL in rejected[0]["reason"]
    assert CURRENT_FLOOR_CONTRACT in rejected[0]["reason"]


def test_handoff_floor_guard_is_scoped_and_restores_all_planner_hooks(tmp_path: Path, monkeypatch) -> None:
    authority = floor.component.authority
    policy = authority.policy
    original_existing = authority.enforce_existing_authority
    original_rescue = policy._rescue_candidates
    original_interrupted = policy._interrupted_candidates

    def fake_component_build_plan(**_kwargs):
        assert authority.enforce_existing_authority is floor.enforce_existing_authority
        assert policy._rescue_candidates is not original_rescue
        assert policy._interrupted_candidates is not original_interrupted
        return {"path": "fresh-profiled-physical-preflight"}

    monkeypatch.setattr(floor.component, "build_plan", fake_component_build_plan)
    assert floor.build_plan(repo_root=tmp_path) == {"path": "fresh-profiled-physical-preflight"}
    assert authority.enforce_existing_authority is original_existing
    assert policy._rescue_candidates is original_rescue
    assert policy._interrupted_candidates is original_interrupted
