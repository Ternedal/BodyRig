from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from bodyrig import sith_fitter_orchestrator, sith_reconstruct, wsl_process


def test_file_capture_avoids_pipes_and_decodes_external_bytes(monkeypatch):
    observed: dict[str, object] = {}

    def fake_run(argv, **kwargs):
        observed["argv"] = list(argv)
        observed.update(kwargs)
        assert kwargs["stdout"] is not subprocess.PIPE
        assert kwargs["stderr"] is not subprocess.PIPE
        assert kwargs["stdout"].seekable()
        assert kwargs["stderr"].seekable()
        assert "text" not in kwargs
        kwargs["stdout"].write(b"ready\x81\n")
        kwargs["stderr"].write(b"warning\xff\n")
        return subprocess.CompletedProcess(list(argv), 7)

    monkeypatch.setattr(wsl_process.subprocess, "run", fake_run)

    completed = wsl_process.run_wsl_file_capture(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "/bin/true"],
        timeout=86_400,
    )

    assert completed.returncode == 7
    assert completed.stdout == "ready�\n"
    assert completed.stderr == "warning�\n"
    assert observed["stdin"] is subprocess.DEVNULL
    assert observed["shell"] is False
    assert observed["check"] is False
    assert observed["timeout"] == 86_400


def test_file_capture_returns_before_inherited_stdio_descendant_exits():
    descendant = "import time; time.sleep(3)"
    parent = (
        "import subprocess,sys; "
        "subprocess.Popen([sys.executable,'-c',sys.argv[1]]); "
        "print('parent-done', flush=True)"
    )

    started = time.monotonic()
    completed = wsl_process.run_wsl_file_capture(
        [sys.executable, "-c", parent, descendant],
        timeout=10,
    )
    elapsed = time.monotonic() - started

    assert completed.returncode == 0
    assert completed.stdout.strip() == "parent-done"
    assert elapsed < 1.5


def test_reconstruct_wsl_boundary_delegates_with_exact_invocation(monkeypatch):
    observed: dict[str, object] = {}

    def fake_capture(command, *, timeout):
        observed["command"] = list(command)
        observed["timeout"] = timeout
        return subprocess.CompletedProcess(list(command), 0, "ok\n", "")

    monkeypatch.setattr(sith_reconstruct, "run_wsl_file_capture", fake_capture)

    completed = sith_reconstruct._run_wsl(
        wsl_exe="wsl.exe",
        distribution="Ubuntu-22.04",
        cwd="/opt/sith",
        command=["/opt/sith/.venv/bin/python", "fit.py"],
        timeout=1234,
    )

    assert completed.stdout == "ok\n"
    assert observed == {
        "command": [
            "wsl.exe",
            "-d",
            "Ubuntu-22.04",
            "--cd",
            "/opt/sith",
            "--",
            "/opt/sith/.venv/bin/python",
            "fit.py",
        ],
        "timeout": 1234,
    }


def test_final_bridge_boundary_uses_shared_file_capture(monkeypatch):
    observed: dict[str, object] = {}

    def fake_capture(command, *, timeout):
        observed["command"] = list(command)
        observed["timeout"] = timeout
        return subprocess.CompletedProcess(list(command), 0, "bridge ok\n", "")

    monkeypatch.setattr(sith_fitter_orchestrator, "run_wsl_file_capture", fake_capture)

    completed = sith_fitter_orchestrator._run(
        ["wsl.exe", "-d", "Ubuntu-22.04", "--", "/bin/true"],
        timeout=4321,
    )

    assert completed.stdout == "bridge ok\n"
    assert observed["command"] == [
        "wsl.exe",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/bin/true",
    ]
    assert observed["timeout"] == 4321


def test_builtin_sith_fitter_outer_timeout_remains_24_hours():
    source = (Path(__file__).resolve().parents[1] / "clone-body-from-stash.ps1").read_text(
        encoding="utf-8"
    )
    start = source.index("if ($usingBuiltInFitter) {")
    end = source.index("$selectArgs = @(", start)
    built_in_fitter = source[start:end]

    assert "timeout_seconds = 86400" in built_in_fitter
