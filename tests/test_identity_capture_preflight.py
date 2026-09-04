from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import bodyrig.identity_capture_preflight as preflight


def _completed(command, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def _good_probe() -> dict:
    return {
        "cv2_import": True,
        "numpy_import": True,
        "cv2_version": "4.10.0",
        "numpy_version": "2.1.0",
        "hog_people_detector": True,
        "haar_frontal": True,
        "haar_profile": True,
        "grabcut": True,
    }


def test_identity_capture_preflight_requires_all_capabilities(monkeypatch):
    calls = []

    def fake_run(command, *, timeout=30):
        calls.append(list(command))
        assert "-c" in command
        return _completed(command, stdout=json.dumps(_good_probe()))

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(external_python=sys.executable)

    assert result["ok"] is True
    assert result["errors"] == []
    assert len(calls) == 1
    assert "-c" in calls[0]


def test_identity_capture_preflight_runs_linux_python_through_wsl(monkeypatch):
    calls = []

    def fake_run(command, *, timeout=30):
        calls.append(list(command))
        return _completed(command, stdout=json.dumps(_good_probe()))

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(
        external_python="/home/anders/.local/share/bodyrig/recovery/venv/bin/python",
        distribution="Ubuntu-22.04",
        wsl_exe=r"C:\Windows\System32\wsl.exe",
    )

    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][:5] == [
        r"C:\Windows\System32\wsl.exe",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/anders/.local/share/bodyrig/recovery/venv/bin/python",
    ]
    assert calls[0][5] == "-c"


def test_identity_capture_preflight_fails_closed_on_missing_numpy_or_grabcut(monkeypatch):
    def fake_run(command, *, timeout=30):
        probe = _good_probe()
        probe["numpy_import"] = False
        probe["grabcut"] = False
        return _completed(command, stdout=json.dumps(probe))

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(external_python=sys.executable)

    assert result["ok"] is False
    assert "identity capture capability missing: numpy_import" in result["errors"]
    assert "identity capture capability missing: grabcut" in result["errors"]


def test_identity_capture_preflight_rejects_invalid_probe_json(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "_run",
        lambda command, timeout=30: _completed(command, stdout="not-json"),
    )
    result = preflight.run_preflight(external_python=sys.executable)
    assert result["ok"] is False
    assert "identity capture capability probe returned invalid JSON" in result["errors"]


def test_identity_capture_preflight_rejects_missing_python(tmp_path: Path):
    with pytest.raises(preflight.IdentityCapturePreflightError, match="Python not found"):
        preflight.run_preflight(external_python=str(tmp_path / "missing-python"))


def test_identity_capture_preflight_rejects_non_linux_python_in_wsl_mode():
    with pytest.raises(preflight.IdentityCapturePreflightError, match="absolute Linux path"):
        preflight.run_preflight(
            external_python=r"C:\python.exe",
            distribution="Ubuntu-22.04",
        )
