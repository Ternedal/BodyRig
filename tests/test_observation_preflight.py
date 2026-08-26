from __future__ import annotations

import json
import subprocess
import sys

import pytest

import bodyrig.observation_preflight as preflight


def _completed(command, *, stdout="", stderr="", returncode=0):
    return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)


def _is_python_probe(command) -> bool:
    return "-c" in command and command[0] != "ffmpeg"


def _good_probe() -> dict:
    return {
        "cv2_import": True,
        "cv2_version": "4.10.0",
        "hog_people_detector": True,
        "haar_frontal": True,
        "haar_profile": True,
    }


def test_preflight_requires_all_opencv_capabilities_and_ffmpeg(monkeypatch):
    calls = []

    def fake_run(command, *, timeout=30):
        calls.append(list(command))
        if _is_python_probe(command):
            return _completed(command, stdout=json.dumps(_good_probe()))
        return _completed(command, stdout="ffmpeg version 7.1 fixture\n")

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(external_python=sys.executable, ffmpeg="ffmpeg")

    assert result["ok"] is True
    assert result["errors"] == []
    assert result["mode"] == "opencv+ffmpeg"
    assert len(calls) == 2
    assert "-c" in calls[0]
    assert calls[1] == ["ffmpeg", "-hide_banner", "-version"]


def test_preflight_runs_opencv_probe_through_wsl_but_keeps_ffmpeg_on_windows(monkeypatch):
    calls = []

    def fake_run(command, *, timeout=30):
        calls.append(list(command))
        if command[0] == "ffmpeg.exe":
            return _completed(command, stdout="ffmpeg version 7.1 fixture\n")
        return _completed(command, stdout=json.dumps(_good_probe()))

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(
        external_python="/home/anders/.local/share/bodyrig/recovery/venv/bin/python",
        ffmpeg="ffmpeg.exe",
        distribution="Ubuntu-22.04",
        wsl_exe=r"C:\Windows\System32\wsl.exe",
    )

    assert result["ok"] is True
    assert calls[0][:5] == [
        r"C:\Windows\System32\wsl.exe",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/anders/.local/share/bodyrig/recovery/venv/bin/python",
    ]
    assert calls[0][5] == "-c"
    assert calls[1] == ["ffmpeg.exe", "-hide_banner", "-version"]


def test_custom_analyzer_preflight_skips_opencv_but_keeps_ffmpeg_gate(monkeypatch):
    calls = []

    def fake_run(command, *, timeout=30):
        calls.append(list(command))
        assert command[0] == "ffmpeg"
        return _completed(command, stdout="ffmpeg version 7.1 fixture\n")

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(
        external_python=sys.executable,
        ffmpeg="ffmpeg",
        require_opencv=False,
    )

    assert result["ok"] is True
    assert result["mode"] == "ffmpeg-only"
    assert "opencv" not in result["checks"]
    assert calls == [["ffmpeg", "-hide_banner", "-version"]]


def test_preflight_fails_closed_when_haar_or_hog_is_missing(monkeypatch):
    def fake_run(command, *, timeout=30):
        if _is_python_probe(command):
            probe = _good_probe()
            probe["hog_people_detector"] = False
            probe["haar_profile"] = False
            return _completed(command, stdout=json.dumps(probe))
        return _completed(command, stdout="ffmpeg version fixture\n")

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(external_python=sys.executable, ffmpeg="ffmpeg")

    assert result["ok"] is False
    assert "OpenCV observation capability missing: hog_people_detector" in result["errors"]
    assert "OpenCV observation capability missing: haar_profile" in result["errors"]


def test_preflight_fails_when_ffmpeg_does_not_identify_itself(monkeypatch):
    def fake_run(command, *, timeout=30):
        if _is_python_probe(command):
            return _completed(command, stdout=json.dumps(_good_probe()))
        return _completed(command, stdout="not ffmpeg\n")

    monkeypatch.setattr(preflight, "_run", fake_run)
    result = preflight.run_preflight(external_python=sys.executable, ffmpeg="ffmpeg")
    assert result["ok"] is False
    assert result["checks"]["ffmpeg"]["available"] is False


def test_preflight_rejects_missing_external_python(tmp_path):
    with pytest.raises(preflight.ObservationPreflightError, match="Python not found"):
        preflight.run_preflight(external_python=str(tmp_path / "missing-python"), ffmpeg="ffmpeg")


def test_preflight_rejects_non_linux_python_in_wsl_mode():
    with pytest.raises(preflight.ObservationPreflightError, match="absolute Linux path"):
        preflight.run_preflight(
            external_python=r"C:\python.exe",
            ffmpeg="ffmpeg",
            distribution="Ubuntu-22.04",
        )
