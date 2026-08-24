from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.ui_jobs as ui_jobs_module


def _job(tmp_path: Path, *, status: str) -> dict:
    job_id = "job-cancel-race"
    root = tmp_path / "jobs" / job_id
    return {
        "format": ui_jobs_module.FORMAT,
        "version": ui_jobs_module.VERSION,
        "job_id": job_id,
        "kind": "body-build",
        "person_id": "person-cancel-race",
        "status": status,
        "created_utc": "2026-08-24T00:00:00Z",
        "started_utc": None,
        "completed_utc": None,
        "bodyrig_revision": "a" * 40,
        "pid": None,
        "session_report": str(root / "physical-session.json"),
        "clone_output": str(root / "clone-output"),
        "acceptance_dir": str(root / "acceptance"),
        "log_path": str(root / "job.log"),
        "adjustment_request": None,
        "adjustment_feedback_sha256": None,
        "body_feedback": "",
        "body_revision": None,
        "canonical_body_id": None,
        "error": None,
    }


def _manager(tmp_path: Path, monkeypatch) -> ui_jobs_module.UiJobManager:
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(ui_jobs_module, "ui_jobs_dir", lambda: jobs)
    return ui_jobs_module.UiJobManager()


def test_canceled_queued_job_cannot_be_resurrected_by_worker(tmp_path: Path, monkeypatch) -> None:
    manager = _manager(tmp_path, monkeypatch)
    job = _job(tmp_path, status="queued")
    ui_jobs_module._write_job(job)

    canceled = manager.cancel(job["job_id"])
    assert canceled["status"] == "canceled"

    def forbidden_powershell() -> str:
        raise AssertionError("canceled queued job reached PowerShell startup")

    monkeypatch.setattr(ui_jobs_module, "_powershell", forbidden_powershell)
    manager._run_body_build(job["job_id"])

    persisted = manager.get(job["job_id"])
    assert persisted["status"] == "canceled"
    assert persisted["started_utc"] is None
    assert persisted["error"] == "Canceled by operator before physical subprocess start"


def test_run_command_refuses_subprocess_after_cancel(tmp_path: Path, monkeypatch) -> None:
    manager = _manager(tmp_path, monkeypatch)
    job = _job(tmp_path, status="canceled")
    job["completed_utc"] = "2026-08-24T00:00:01Z"
    job["error"] = "Canceled by operator before physical subprocess start"
    ui_jobs_module._write_job(job)

    def forbidden_popen(*args, **kwargs):
        raise AssertionError("Popen was called for a canceled UI job")

    monkeypatch.setattr(ui_jobs_module.subprocess, "Popen", forbidden_popen)
    with pytest.raises(ui_jobs_module.UiJobError, match="no longer running"):
        manager._run_command(job, ["pwsh", "-NoProfile", "-Command", "exit 0"])

    persisted = manager.get(job["job_id"])
    assert persisted["status"] == "canceled"
    assert persisted["pid"] is None


def test_running_physical_job_cannot_be_marked_canceled(tmp_path: Path, monkeypatch) -> None:
    manager = _manager(tmp_path, monkeypatch)
    job = _job(tmp_path, status="running")
    job["started_utc"] = "2026-08-24T00:00:01Z"
    job["pid"] = 4242
    ui_jobs_module._write_job(job)

    class ActiveProcess:
        pid = 4242

        def poll(self):
            return None

        def terminate(self):
            raise AssertionError("running physical process must not be falsely terminated/marked canceled")

    manager._processes[job["job_id"]] = ActiveProcess()  # type: ignore[assignment]

    with pytest.raises(ui_jobs_module.UiJobError, match="cannot be safely canceled"):
        manager.cancel(job["job_id"])

    persisted = manager.get(job["job_id"])
    assert persisted["status"] == "running"
    assert persisted["pid"] == 4242
    assert persisted["completed_utc"] is None


def test_worker_failure_never_overwrites_terminal_state() -> None:
    source = Path("bodyrig/ui_jobs.py").read_text(encoding="utf-8")
    assert 'if job.get("status") not in _FINAL:' in source
    assert 'if current.get("status") != "running":' in source
    assert 'if job.get("status") == "running":' in source
    assert "WSL/child-process termination cannot be proven" in source
