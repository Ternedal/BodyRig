from __future__ import annotations

from pathlib import Path

import bodyrig.rig_window_authority_policy as authority
import bodyrig.rig_window_policy as policy


HEAD = "a" * 40
HISTORICAL = "b" * 40


def _candidate(*, kind: str, gate: str, rank: int, acceptance_dir: str, state: str = "ready", revision: str = HEAD):
    return {
        "kind": kind,
        "gate": gate,
        "rank": rank,
        "stamp": "2026-01-01T00:00:00Z",
        "preferred": False,
        "acceptance_dir": acceptance_dir,
        "state": state,
        "evidence_revision": revision,
    }


def test_committed_gate_a_outranks_validatable_rescue(tmp_path: Path, monkeypatch) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    (acceptance / "bodyrig-acceptance.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(authority.policy.base, "_head", lambda _root: HEAD)
    existing, rejected = authority.enforce_existing_authority(
        repo_root=tmp_path,
        candidates=[
            _candidate(
                kind="ui-acceptance",
                gate="gate-a",
                rank=10,
                acceptance_dir=str(acceptance),
            )
        ],
        rejected=[],
    )

    assert rejected == []
    assert existing[0]["rank"] == authority.COMMITTED_GATE_A_RANK == 16
    ranked = policy.rank_physical_candidates(
        existing
        + [
            {
                "kind": "gate-a-rescue",
                "rank": policy.RESCUE_RANK,
                "preferred": True,
                "stamp": "2099-01-01T00:00:00Z",
            }
        ]
    )
    assert ranked[0]["kind"] == "ui-acceptance"


def test_pre_gate_a_session_is_not_misclassified_as_committed_gate_a(tmp_path: Path, monkeypatch) -> None:
    prospective = tmp_path / "clone-output" / "acceptance"
    monkeypatch.setattr(authority.policy.base, "_head", lambda _root: HEAD)

    existing, rejected = authority.enforce_existing_authority(
        repo_root=tmp_path,
        candidates=[
            _candidate(
                kind="physical-session",
                gate="gate-a",
                rank=policy.SESSION_RANK,
                acceptance_dir=str(prospective),
            )
        ],
        rejected=[],
    )

    assert rejected == []
    assert existing[0]["rank"] == policy.SESSION_RANK == 10
    assert not prospective.exists()


def test_unsafe_complete_historical_acceptance_is_rejected_before_selection(tmp_path: Path, monkeypatch) -> None:
    acceptance = tmp_path / "historical-acceptance"
    acceptance.mkdir()
    (acceptance / "bodyrig-acceptance.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(authority.policy.base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(authority, "_strict_complete_historical_revision_is_safe", lambda _root, _revision: False)

    kept, rejected = authority.enforce_existing_authority(
        repo_root=tmp_path,
        candidates=[
            _candidate(
                kind="ui-acceptance",
                gate="release",
                rank=100,
                acceptance_dir=str(acceptance),
                state="complete",
                revision=HISTORICAL,
            )
        ],
        rejected=[],
    )

    assert kept == []
    assert len(rejected) == 1
    assert "not proven as an ancestor" in rejected[0]["reason"]


def test_safe_complete_historical_acceptance_remains_eligible(tmp_path: Path, monkeypatch) -> None:
    acceptance = tmp_path / "historical-acceptance"
    acceptance.mkdir()
    (acceptance / "bodyrig-acceptance.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(authority.policy.base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(authority, "_strict_complete_historical_revision_is_safe", lambda _root, _revision: True)

    kept, rejected = authority.enforce_existing_authority(
        repo_root=tmp_path,
        candidates=[
            _candidate(
                kind="ui-acceptance",
                gate="release",
                rank=100,
                acceptance_dir=str(acceptance),
                state="complete",
                revision=HISTORICAL,
            )
        ],
        rejected=[],
    )

    assert rejected == []
    assert kept[0]["state"] == "complete"
    assert kept[0]["evidence_revision"] == HISTORICAL


def test_terminal_historical_authority_fails_closed_when_origin_main_ref_is_missing(tmp_path: Path, monkeypatch) -> None:
    class Result:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(authority.policy.base, "_git", lambda *_args: Result())
    assert authority._strict_complete_historical_revision_is_safe(tmp_path, HISTORICAL) is False


def test_authority_guard_restores_legacy_policy_hook_after_call(monkeypatch) -> None:
    original = policy._existing_candidates

    def fake_build_plan(**_kwargs):
        assert policy._existing_candidates is authority._guarded_existing_candidates
        return {"ok": True}

    monkeypatch.setattr(policy, "build_plan", fake_build_plan)
    assert authority.build_plan(repo_root=Path(".")) == {"ok": True}
    assert policy._existing_candidates is original
