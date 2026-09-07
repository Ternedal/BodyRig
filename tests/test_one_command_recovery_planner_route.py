from pathlib import Path

import pytest

import bodyrig.rig_window_authority_policy as authority


REVISION = "a" * 40


def _live_status() -> dict:
    return {
        "state": "ready",
        "gate": "interrupted-fit-recovery",
        "progress_rank": 5,
        "recovery_mode": "resume-fit-only",
        "fitter_rerun": True,
        "expensive_reconstruction_rerun": False,
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "body_id": "fixture-person",
        "run_root": r"C:\BodyRig\automatic-production\fixture",
        "session_report": r"C:\BodyRig\automatic-production\fixture\bodyrig-physical-clone-session.json",
        "clone_output": r"C:\BodyRig\automatic-production\fixture\clone-output",
        "identity_workspace": r"C:\BodyRig\identity-workspaces\fixture",
        "message": "same reconstruction is reusable",
        "next_command": r".\resume-interrupted-physical-fit.ps1 -FailedSessionReport 'fixture'",
    }


def test_current_session_hook_returns_interrupted_fit_resume_before_legacy_blocked_status(tmp_path: Path, monkeypatch) -> None:
    session = tmp_path / "bodyrig-physical-clone-session.json"
    session.write_text("{}\n", encoding="utf-8")
    legacy_called = False

    def legacy(_session: Path, _repo: Path):
        nonlocal legacy_called
        legacy_called = True
        raise AssertionError("legacy session status must not win over validated one-command recovery")

    monkeypatch.setattr(authority, "build_live_recovery_status", lambda _session, _repo: _live_status())
    monkeypatch.setattr(authority, "_ORIGINAL_CURRENT_SESSION_STATUS", legacy)

    status = authority._guarded_current_session_status(session, tmp_path)
    assert legacy_called is False
    assert status.state == "ready"
    assert status.gate == "interrupted-fit-recovery"
    assert status.bodyrig_revision == REVISION
    assert "resume-interrupted-physical-fit.ps1" in str(status.next_command)


def test_current_session_hook_fails_closed_for_invalid_recovery_receipt(tmp_path: Path, monkeypatch) -> None:
    session = tmp_path / "bodyrig-physical-clone-session.json"
    session.write_text("{}\n", encoding="utf-8")

    def invalid(_session: Path, _repo: Path):
        raise authority.OneCommandRecoveryError("tampered producer receipt")

    monkeypatch.setattr(authority, "build_live_recovery_status", invalid)
    with pytest.raises(authority.policy.base.RigWindowPlanError, match="tampered producer receipt"):
        authority._guarded_current_session_status(session, tmp_path)
