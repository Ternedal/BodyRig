from __future__ import annotations

from pathlib import Path

import bodyrig.rig_window_policy as policy


HEAD = "a" * 40
HISTORICAL = "b" * 40


def test_downstream_acceptance_beats_gate_a_rescue_even_when_rescue_is_newer() -> None:
    ranked = policy.rank_physical_candidates(
        [
            {
                "kind": "gate-a-rescue",
                "rank": policy.RESCUE_RANK,
                "preferred": False,
                "stamp": "2099-01-01T00:00:00Z",
            },
            {
                "kind": "ui-acceptance",
                "rank": 50,
                "preferred": False,
                "stamp": "2026-01-01T00:00:00Z",
            },
        ]
    )
    assert ranked[0]["kind"] == "ui-acceptance"


def test_validated_gate_a_rescue_beats_plain_completed_session() -> None:
    ranked = policy.rank_physical_candidates(
        [
            {"kind": "physical-session", "rank": policy.SESSION_RANK, "preferred": False, "stamp": "2099"},
            {"kind": "gate-a-rescue", "rank": policy.RESCUE_RANK, "preferred": False, "stamp": "2026"},
        ]
    )
    assert ranked[0]["kind"] == "gate-a-rescue"


def test_completed_session_beats_interrupted_package_or_fit_recovery() -> None:
    ranked = policy.rank_physical_candidates(
        [
            {"kind": "interrupted-body-recovery", "rank": policy.INTERRUPTED_ADOPT_RANK, "preferred": True, "stamp": "2099"},
            {"kind": "physical-session", "rank": policy.SESSION_RANK, "preferred": False, "stamp": "2026"},
            {"kind": "interrupted-body-recovery", "rank": policy.INTERRUPTED_FIT_RANK, "preferred": False, "stamp": "2099"},
        ]
    )
    assert ranked[0]["kind"] == "physical-session"


def test_preferred_job_only_breaks_same_progress_ties() -> None:
    ranked = policy.rank_physical_candidates(
        [
            {"kind": "a", "rank": 15, "preferred": False, "stamp": "2099"},
            {"kind": "b", "rank": 15, "preferred": True, "stamp": "2026"},
        ]
    )
    assert ranked[0]["kind"] == "b"


def test_historical_session_emits_exact_revision_continuation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(policy.base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(policy.base, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(policy.base, "_job_rows", lambda _root: [])
    monkeypatch.setattr(
        policy.base,
        "resolve_person_scope",
        lambda **_kwargs: ("", "performer-7"),
    )
    monkeypatch.setattr(
        policy.base,
        "_scope_rows",
        lambda rows, **_kwargs: rows,
    )
    monkeypatch.setattr(
        policy,
        "_existing_candidates",
        lambda **_kwargs: (
            [
                {
                    "kind": "physical-session",
                    "rank": policy.SESSION_RANK,
                    "stamp": "2026-01-01T00:00:00Z",
                    "preferred": False,
                    "session_report": r"C:\BodyRig\session.json",
                    "state": "ready",
                    "gate": "gate-a",
                    "acceptance_dir": None,
                    "evidence_revision": HISTORICAL,
                    "performer_id": "performer-7",
                    "body_id": "body-seven",
                }
            ],
            [],
        ),
    )
    monkeypatch.setattr(policy, "_rescue_candidates", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(policy, "_interrupted_candidates", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(policy.base, "_historical_revision_is_safe", lambda _root, _revision: True)

    plan = policy.build_plan(repo_root=tmp_path)

    assert plan["path"] == "historical-physical-session-checkout"
    assert plan["evidence_revision"] == HISTORICAL
    assert plan["expensive_reconstruction_rerun"] is False
    assert plan["fitter_rerun"] is False
    assert f"-Revision '{HISTORICAL}' -NoBrowser" in plan["next_command"]
    assert "-SessionReport 'C:\\BodyRig\\session.json'" in plan["next_command"]


def test_no_candidate_is_the_only_path_that_allows_fresh_reconstruction(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(policy.base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(policy.base, "data_dir", lambda: tmp_path)
    monkeypatch.setattr(policy.base, "_job_rows", lambda _root: [])
    monkeypatch.setattr(policy.base, "resolve_person_scope", lambda **_kwargs: ("", "performer-7"))
    monkeypatch.setattr(policy.base, "_scope_rows", lambda rows, **_kwargs: rows)
    monkeypatch.setattr(policy, "_existing_candidates", lambda **_kwargs: ([], []))
    monkeypatch.setattr(policy, "_rescue_candidates", lambda *_args, **_kwargs: ([], []))
    monkeypatch.setattr(policy, "_interrupted_candidates", lambda *_args, **_kwargs: ([], []))

    plan = policy.build_plan(
        repo_root=tmp_path,
        performer_id="performer-7",
        body_id="body-seven",
    )

    assert plan["path"] == "fresh-profiled-physical-preflight"
    assert plan["progress_rank"] == 0
    assert plan["expensive_reconstruction_rerun"] is True
    assert plan["fitter_rerun"] is True
