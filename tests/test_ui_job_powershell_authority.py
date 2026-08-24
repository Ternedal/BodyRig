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
    monkeypatch.setattr(ui_jobs_module.shutil, "which", lambda name: "C:/Program Files/PowerShell/7/pwsh.exe" if name == "pwsh" else None)
    assert ui_jobs_module._powershell() == "C:/Program Files/PowerShell/7/pwsh.exe"


def test_operator_checkout_status_requires_pwsh_major_seven_or_newer() -> None:
    source = Path("bodyrig/ui_jobs.py").read_text(encoding="utf-8")
    assert 'shutil.which("pwsh")' in source
    assert 'shutil.which("powershell")' not in source
    assert '$PSVersionTable.PSVersion.Major' in source
    assert 'int(major_raw) < 7' in source
    assert '"powershell_major": int(major_raw)' in source
