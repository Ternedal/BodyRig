from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import bodyrig.identity_capture_preflight as preflight


def _completed(command, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def test_identity_capture_preflight_requires_all_capabilities(monkeypatch):
    calls = []

    def fake_run(command, *, timeout=30):
        calls.append(list(command))
        assert "-c" in command
        return _completed(
            command,
            stdout=json.dumps(
                {
                    "cv2_import": True,
                    "numpy_import": True,
                    "cv2_version": "4.10.0",
                    "numpy_version": "2.1.0",
                    "hog_people_detector": True,
                    "haar_frontal": True,
                    "haar_profile": True,
                    "grabcut": True,
                }
            ),
        )

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(external_python=sys.executable)

    assert result["ok"] is True
    assert result["errors"] == []
    assert len(calls) == 1
    assert "-c" in calls[0]


def test_identity_capture_preflight_fails_closed_on_missing_numpy_or_grabcut(monkeypatch):
    def fake_run(command, *, timeout=30):
        return _completed(
            command,
            stdout=json.dumps(
                {
                    "cv2_import": True,
                    "numpy_import": False,
                    "cv2_version": "4.10.0",
                    "numpy_version": "unknown",
                    "hog_people_detector": True,
                    "haar_frontal": True,
                    "haar_profile": True,
                    "grabcut": False,
                }
            ),
        )

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
