from __future__ import annotations

import json
import subprocess
import sys

import pytest

import bodyrig.observation_preflight as preflight


def _completed(command, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def test_preflight_requires_all_opencv_capabilities_and_ffmpeg(monkeypatch):
    calls = []

    def fake_run(command, *, timeout=30):
        calls.append(list(command))
        if command[0] == sys.executable:
            return _completed(
                command,
                stdout=json.dumps(
                    {
                        "cv2_import": True,
                        "cv2_version": "4.10.0",
                        "hog_people_detector": True,
                        "haar_frontal": True,
                        "haar_profile": True,
                    }
                ),
            )
        return _completed(command, stdout="ffmpeg version 7.1 fixture\n")

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(external_python=sys.executable, ffmpeg="ffmpeg")

    assert result["ok"] is True
    assert result["errors"] == []
    assert len(calls) == 2
    assert calls[0][0] == sys.executable
    assert calls[1] == ["ffmpeg", "-hide_banner", "-version"]


def test_preflight_fails_closed_when_haar_or_hog_is_missing(monkeypatch):
    def fake_run(command, *, timeout=30):
        if command[0] == sys.executable:
            return _completed(
                command,
                stdout=json.dumps(
                    {
                        "cv2_import": True,
                        "cv2_version": "4.10.0",
                        "hog_people_detector": False,
                        "haar_frontal": True,
                        "haar_profile": False,
                    }
                ),
            )
        return _completed(command, stdout="ffmpeg version fixture\n")

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(external_python=sys.executable, ffmpeg="ffmpeg")

    assert result["ok"] is False
    assert "OpenCV observation capability missing: hog_people_detector" in result["errors"]
    assert "OpenCV observation capability missing: haar_profile" in result["errors"]


def test_preflight_fails_when_ffmpeg_does_not_identify_itself(monkeypatch):
    def fake_run(command, *, timeout=30):
        if command[0] == sys.executable:
            return _completed(
                command,
                stdout=json.dumps(
                    {
                        "cv2_import": True,
                        "cv2_version": "4.10.0",
                        "hog_people_detector": True,
                        "haar_frontal": True,
                        "haar_profile": True,
                    }
                ),
            )
        return _completed(command, stdout="not ffmpeg\n")

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(external_python=sys.executable, ffmpeg="ffmpeg")
    assert result["ok"] is False
    assert result["checks"]["ffmpeg"]["available"] is False


def test_preflight_rejects_missing_external_python(tmp_path):
    with pytest.raises(preflight.ObservationPreflightError, match="Python not found"):
        preflight.run_preflight(external_python=str(tmp_path / "missing-python"), ffmpeg="ffmpeg")
