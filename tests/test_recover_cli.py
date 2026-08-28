from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

import bodyrig.recover_cli as recover_cli
from bodyrig.bridges.hmr2_config import ADAPTER_NAME, ADAPTER_REVISION
from bodyrig.recover_cli import _select_track
from bodyrig.recovery import RecoveredTrack, RecoveryFrame, RecoveryResult


def track(name, count=2):
    frames = tuple(RecoveryFrame(timestamp_ms=i * 40, joints={"head": (0.0, 1.0, 0.0)}) for i in range(count))
    return RecoveredTrack(track_id=name, frames=frames)


def result(*tracks):
    return RecoveryResult(tracks=tracks, adapter="fixture", revision="v1")


def test_single_track_auto_selects():
    assert _select_track(result(track("s00-t1")), None).track_id == "s00-t1"


def test_multiple_tracks_require_explicit_selection():
    with pytest.raises(ValueError, match="multiple"):
        _select_track(result(track("s00-t1"), track("s00-t2")), None)


def test_explicit_track_selection():
    selected = _select_track(result(track("s00-t1"), track("s00-t2")), "s00-t2")
    assert selected.track_id == "s00-t2"


def test_unknown_track_reports_candidates():
    with pytest.raises(ValueError, match="available"):
        _select_track(result(track("s00-t1")), "missing")


def test_wsl_recovery_translates_bridge_and_source_paths_before_invocation(monkeypatch):
    conversions = []

    def fake_converter(value: str) -> str:
        conversions.append(value)
        if value.endswith("hmr2_4dhumans_bridge.py"):
            return "/mnt/c/bodyrig/hmr2_4dhumans_bridge.py"
        if value.endswith("segment-01.mp4"):
            return "/mnt/c/bodyrig/segment-01.mp4"
        raise AssertionError(f"unexpected path conversion: {value}")

    monkeypatch.setattr(
        recover_cli,
        "make_wsl_path_converter",
        lambda wsl_exe, distribution: fake_converter,
    )

    calls = []

    def fake_run(command, **kwargs):
        calls.append((list(command), kwargs))
        request = json.loads(kwargs["input"])
        assert request == {
            "format": "bodyrig-recovery-request",
            "version": 1,
            "sources": ["/mnt/c/bodyrig/segment-01.mp4"],
        }
        payload = {
            "format": "bodyrig-recovery",
            "version": 1,
            "adapter": ADAPTER_NAME,
            "revision": ADAPTER_REVISION,
            "tracks": [
                {
                    "track_id": "s00-t1",
                    "frames": [
                        {"timestamp_ms": 0, "joints": {"head": [0.0, 1.0, 0.0]}},
                        {"timestamp_ms": 40, "joints": {"head": [0.0, 1.0, 0.0]}},
                    ],
                }
            ],
        }
        return subprocess.CompletedProcess(command, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(recover_cli.subprocess, "run", fake_run)

    recovered = recover_cli._recover_wsl(
        sources=[Path(r"C:\BodyRig\segment-01.mp4")],
        external_python="/home/anders/.local/share/bodyrig/recovery/venv/bin/python",
        repo="/home/anders/.local/share/bodyrig/recovery/4D-Humans",
        phalp_repo="/home/anders/.local/share/bodyrig/recovery/PHALP",
        distribution="Ubuntu-22.04",
        wsl_exe=r"C:\Windows\System32\wsl.exe",
    )

    assert recovered.adapter == ADAPTER_NAME
    assert recovered.revision == ADAPTER_REVISION
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert kwargs["text"] is True
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert "timeout" not in kwargs
    assert command[:5] == [
        r"C:\Windows\System32\wsl.exe",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/anders/.local/share/bodyrig/recovery/venv/bin/python",
    ]
    assert "/mnt/c/bodyrig/hmr2_4dhumans_bridge.py" in command
    assert command[-4:] == [
        "--repo",
        "/home/anders/.local/share/bodyrig/recovery/4D-Humans",
        "--phalp-repo",
        "/home/anders/.local/share/bodyrig/recovery/PHALP",
    ]
    assert len(conversions) == 2


def test_wsl_recovery_rejects_windows_recovery_authority_paths():
    with pytest.raises(Exception, match="absolute Linux path"):
        recover_cli._recover_wsl(
            sources=[Path("segment.mp4")],
            external_python=r"C:\python.exe",
            repo="/home/anders/4D-Humans",
            phalp_repo="/home/anders/PHALP",
            distribution="Ubuntu-22.04",
            wsl_exe="wsl.exe",
        )
