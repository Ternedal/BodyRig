from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import bodyrig.wsl_log_handle_smoke as smoke


ROOT = Path(__file__).resolve().parents[1]


def test_target_smoke_selects_canonical_python_commands() -> None:
    assert smoke._linux_python_from_command(["--", "/opt/bodyrig/venv/bin/python", "adapter.py"]) == "/opt/bodyrig/venv/bin/python"
    assert smoke._linux_python_from_command(["python3.10", "adapter.py"]) == "python3.10"
    assert smoke._linux_python_from_command(["/usr/bin/openpose", "--display", "0"]) is None


def test_target_smoke_proves_adapter_log_boundary_without_leaking_handle(monkeypatch) -> None:
    calls = []
    ticks = iter((10.0, 10.2))

    def fake_run(command, **kwargs):
        calls.append((list(command), dict(kwargs)))
        log = kwargs["stdout"]
        log.write(b"bodyrig-wsl-log-smoke\n")
        log.flush()
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(smoke, "_is_windows", lambda: True)
    monkeypatch.setattr(smoke.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(smoke.subprocess, "run", fake_run)

    elapsed = smoke.run_target_wsl_log_handle_smoke(
        wsl_exe=r"C:\Windows\System32\wsl.exe",
        distribution="Ubuntu-22.04",
        linux_command=["/home/bodyrig/recovery/venv/bin/python", "adapter.py"],
    )

    assert elapsed == pytest.approx(0.2)
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command[:3] == [smoke.sys.executable, "-m", "bodyrig.wsl_adapter_bridge"]
    assert command[-3] == "/home/bodyrig/recovery/venv/bin/python"
    assert "bodyrig-wsl-log-smoke" in command[-1]
    assert kwargs["stderr"] is subprocess.STDOUT
    assert kwargs["close_fds"] is True
    assert kwargs["env"][smoke.SMOKE_CHILD_ENV] == "1"


def test_bridge_runs_target_smoke_before_real_wsl_adapter() -> None:
    text = (ROOT / "bodyrig" / "wsl_adapter_bridge.py").read_text(encoding="utf-8")
    smoke_call = "run_target_wsl_log_handle_smoke("
    real_call = "completed = _run_wsl_forward(invocation)"
    assert smoke_call in text
    assert real_call in text
    assert text.index(smoke_call) < text.index(real_call)
    assert 'os.environ.get(SMOKE_CHILD_ENV) != "1"' in text
