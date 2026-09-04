from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.ui_jobs as ui_jobs_module


def test_ui_job_powershell_never_falls_back_to_windows_powershell(monkeypatch) -> None:
    requested: list[str] = []

    def fake_which(name: str):
        requested.append(name)
        return None

    monkeypatch.setattr(ui_jobs_module.shutil, "which", fake_which)
    with pytest.raises(ui_jobs_module.UiJobError, match=r"PowerShell 7\+ executable \(pwsh\) was not found"):
        ui_jobs_module._powershell()

    assert requested == ["pwsh"]


def test_ui_job_powershell_returns_exact_pwsh_path(monkeypatch) -> None:
    monkeypatch.setattr(
        ui_jobs_module.shutil,
        "which",
        lambda name: "C:/Program Files/PowerShell/7/pwsh.exe" if name == "pwsh" else None,
    )
    assert ui_jobs_module._powershell() == "C:/Program Files/PowerShell/7/pwsh.exe"


def test_operator_checkout_status_requires_pwsh_major_seven_or_newer() -> None:
    source = Path("bodyrig/ui_jobs.py").read_text(encoding="utf-8")
    assert 'shutil.which("pwsh")' in source
    assert 'shutil.which("powershell")' not in source
    assert '$PSVersionTable.PSVersion.Major' in source
    assert 'int(major_raw) < 7' in source
    assert '"powershell_major": int(major_raw)' in source


def test_physical_subprocess_refuses_checkout_revision_drift(tmp_path: Path, monkeypatch) -> None:
    jobs = tmp_path / "jobs"
    monkeypatch.setattr(ui_jobs_module, "ui_jobs_dir", lambda: jobs)
    manager = ui_jobs_module.UiJobManager()

    job_id = "job-authority-drift"
    job_root = jobs / job_id
    job = {
        "format": ui_jobs_module.FORMAT,
        "version": ui_jobs_module.VERSION,
        "job_id": job_id,
        "kind": "body-build",
        "person_id": "person-authority-drift",
        "status": "running",
        "created_utc": "2026-08-24T00:00:00Z",
        "started_utc": "2026-08-24T00:00:01Z",
        "completed_utc": None,
        "bodyrig_revision": "a" * 40,
        "pid": None,
        "session_report": str(job_root / "physical-session.json"),
        "clone_output": str(job_root / "clone-output"),
        "acceptance_dir": str(job_root / "acceptance"),
        "log_path": str(job_root / "job.log"),
        "adjustment_request": None,
        "adjustment_feedback_sha256": None,
        "body_feedback": "",
        "body_revision": None,
        "canonical_body_id": None,
        "error": None,
    }
    ui_jobs_module._write_job(job)

    monkeypatch.setattr(
        ui_jobs_module,
        "operator_checkout_status",
        lambda: {
            "ok": True,
            "revision": "b" * 40,
            "root": str(tmp_path),
            "powershell": "pwsh",
            "powershell_major": 7,
        },
    )

    def forbidden_popen(*args, **kwargs):
        raise AssertionError("Popen was called after checkout revision drift")

    monkeypatch.setattr(ui_jobs_module.subprocess, "Popen", forbidden_popen)

    with pytest.raises(ui_jobs_module.UiJobError, match="checkout revision changed after UI job enqueue"):
        manager._run_command(job, ["pwsh", "-NoProfile", "-Command", "exit 0"])

    persisted = manager.get(job_id)
    assert persisted["status"] == "running"
    assert persisted["pid"] is None
