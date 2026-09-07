from pathlib import Path

import bodyrig.one_command_recovery as recovery


REVISION = "a" * 40


def _structural(tmp_path: Path) -> dict:
    run = tmp_path / "run"
    return {
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "body_id": "fixture-person",
        "recovery_mode": "resume-fit-only",
        "run_root": str(run),
        "session_report": str(run / "bodyrig-physical-clone-session.json"),
        "clone_output": str(run / "clone-output"),
        "identity_workspace": str(tmp_path / "identity"),
    }


def _completed(tmp_path: Path) -> dict:
    clone_output = tmp_path / "run" / "clone-output"
    return {
        "state": "complete",
        "gate": "physical-clone",
        "bodyrig_revision": REVISION,
        "performer_id": "42",
        "body_id": "fixture-person",
        "recovery_mode": "resume-fit-only",
        "recovered_session": str(clone_output / "physical-session-recovered.json"),
        "recovery_receipt": str(clone_output / "interrupted-fit-recovery.json"),
        "clone_output": str(clone_output),
        "acceptance_dir": str(clone_output / "acceptance"),
        "expensive_reconstruction_rerun": False,
        "fitter_rerun": False,
    }


def test_committed_gate_a_continues_only_automatic_production(tmp_path: Path, monkeypatch) -> None:
    structural = _structural(tmp_path)
    completed = _completed(tmp_path)
    acceptance = Path(completed["acceptance_dir"])
    acceptance.mkdir(parents=True)
    (acceptance / "bodyrig-acceptance.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(recovery, "inspect_completed_recovery", lambda _structural: completed)
    monkeypatch.setattr(
        recovery,
        "inspect_for_rig_window",
        lambda _acceptance: {
            "state": "ready",
            "gate": "automatic-quest",
            "progress_rank": 35,
            "bodyrig_revision": REVISION,
        },
    )

    status = recovery._completed_downstream_status(structural)
    assert status is not None
    assert status["state"] == "ready"
    assert status["gate"] == "automatic-quest"
    assert status["progress_rank"] == 35
    command = str(status["next_command"])
    assert "run-automatic-production-activation.ps1" in command
    assert "resume-interrupted-physical-fit.ps1" not in command
    assert "accept-physical-clone.ps1" not in command


def test_completed_automatic_release_emits_no_mutating_command(tmp_path: Path, monkeypatch) -> None:
    structural = _structural(tmp_path)
    completed = _completed(tmp_path)
    acceptance = Path(completed["acceptance_dir"])
    acceptance.mkdir(parents=True)
    (acceptance / "bodyrig-acceptance.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(recovery, "inspect_completed_recovery", lambda _structural: completed)
    monkeypatch.setattr(
        recovery,
        "inspect_for_rig_window",
        lambda _acceptance: {
            "state": "complete",
            "gate": "automatic-release",
            "progress_rank": 40,
            "bodyrig_revision": REVISION,
        },
    )

    status = recovery._completed_downstream_status(structural)
    assert status is not None
    assert status["state"] == "complete"
    assert status["gate"] == "automatic-release"
    assert status["progress_rank"] == 40
    assert status["next_command"] is None
