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


def _plan(*, gate: str, revision: str = HEAD, state: str = "ready") -> dict:
    return {
        "format": "bodyrig-rig-window-plan",
        "version": 4,
        "state": state,
        "path": "existing-gate-a-acceptance",
        "bodyrig_revision": HEAD,
        "evidence_revision": revision,
        "acceptance_dir": r"C:\BodyRig\acceptance",
        "gate": gate,
        "progress_rank": 40,
        "next_command": "legacy-command",
        "expensive_reconstruction_rerun": False,
        "fitter_rerun": False,
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


def test_automatic_standalone_acceptance_uses_automatic_progress(tmp_path: Path, monkeypatch) -> None:
    acceptance = tmp_path / "acceptance"
    acceptance.mkdir()
    monkeypatch.setattr(authority.policy.base, "_head", lambda _root: HEAD)
    monkeypatch.setattr(authority, "has_automatic_evidence", lambda _path: True)
    monkeypatch.setattr(
        authority,
        "_automatic_payload",
        lambda _path: {
            "policy_scope": "evidence-revision-automatic-structural",
            "progress_rank": 50,
            "gate": "automatic-quest-quality",
            "state": "ready",
            "bodyrig_revision": HEAD,
        },
    )

    kept, rejected = authority.enforce_existing_authority(
        repo_root=tmp_path,
        candidates=[
            _candidate(
                kind="physical-session",
                gate="quest-probe",
                rank=40,
                acceptance_dir=str(acceptance),
            )
        ],
        rejected=[],
    )

    assert rejected == []
    assert kept[0]["rank"] == 50
    assert kept[0]["gate"] == "automatic-quest-quality"


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


def test_current_automatic_plan_routes_to_resumable_activation(tmp_path: Path) -> None:
    routed = authority._route_automatic_plan(tmp_path, _plan(gate="automatic-quest", revision=HEAD))
    assert routed["path"] == "existing-automatic-production"
    assert "run-automatic-production-activation.ps1" in routed["next_command"]
    assert "run-automatic-reference-windows-proof.ps1" not in routed["next_command"]
    assert routed["expensive_reconstruction_rerun"] is False


def test_historical_automatic_with_resumable_producer_uses_exact_checkout_then_resume(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(authority, "_revision_has_resumable_automatic_tooling", lambda _root, _revision: True)
    routed = authority._route_automatic_plan(tmp_path, _plan(gate="automatic-quest-quality", revision=HISTORICAL))
    assert routed["path"] == "historical-automatic-production"
    assert f"-Revision '{HISTORICAL}'" in routed["next_command"]
    assert "run-automatic-production-activation.ps1" in routed["next_command"]


def test_legacy_historical_windows_pass_continues_at_quest_without_rerunning_windows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(authority, "_revision_has_resumable_automatic_tooling", lambda _root, _revision: False)
    routed = authority._route_automatic_plan(tmp_path, _plan(gate="automatic-quest", revision=HISTORICAL))
    assert routed["path"] == "historical-automatic-production"
    assert "run-automatic-reference-quest-proof.ps1" in routed["next_command"]
    assert "run-automatic-reference-windows-proof.ps1" not in routed["next_command"]
    assert "bodyrig.automatic_release_gate" in routed["next_command"]


def test_legacy_historical_quest_pass_runs_only_release_gate(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(authority, "_revision_has_resumable_automatic_tooling", lambda _root, _revision: False)
    routed = authority._route_automatic_plan(tmp_path, _plan(gate="automatic-release", revision=HISTORICAL))
    assert routed["path"] == "historical-automatic-production"
    assert "bodyrig.automatic_release_gate" in routed["next_command"]
    assert "run-automatic-reference-quest-proof.ps1" not in routed["next_command"]
    assert "run-automatic-reference-windows-proof.ps1" not in routed["next_command"]


def test_legacy_historical_quest_quality_fails_closed_instead_of_rebuilding(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(authority, "_revision_has_resumable_automatic_tooling", lambda _root, _revision: False)
    routed = authority._route_automatic_plan(tmp_path, _plan(gate="automatic-quest-quality", revision=HISTORICAL))
    assert routed["state"] == "blocked"
    assert routed["path"] == "historical-automatic-resume-blocked"
    assert routed["next_command"] is None
    assert routed["expensive_reconstruction_rerun"] is False
    assert "Do not rerun reconstruction" in routed["rationale"]


def test_authority_guard_restores_all_policy_hooks_after_call(monkeypatch) -> None:
    original_existing = policy._existing_candidates
    original_acceptance = policy.base._current_acceptance_status
    original_session = policy.base._current_session_status

    def fake_build_plan(**_kwargs):
        assert policy._existing_candidates is authority._guarded_existing_candidates
        assert policy.base._current_acceptance_status is authority._guarded_current_acceptance_status
        assert policy.base._current_session_status is authority._guarded_current_session_status
        return {"gate": "gate-a"}

    monkeypatch.setattr(policy, "build_plan", fake_build_plan)
    assert authority.build_plan(repo_root=Path(".")) == {"gate": "gate-a"}
    assert policy._existing_candidates is original_existing
    assert policy.base._current_acceptance_status is original_acceptance
    assert policy.base._current_session_status is original_session
