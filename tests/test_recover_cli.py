from __future__ import annotations

import json
import subprocess
import sys
import time
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
        request = json.loads(kwargs["stdin"].read().decode("utf-8"))
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
        kwargs["stdout"].write(json.dumps(payload).encode("utf-8"))
        kwargs["stderr"].write(b"diagnostic \x81 byte")
        return subprocess.CompletedProcess(command, 0)

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
    assert "input" not in kwargs
    assert "text" not in kwargs
    assert "encoding" not in kwargs
    assert "errors" not in kwargs
    assert "timeout" not in kwargs
    assert kwargs["stdin"] is not subprocess.PIPE
    assert kwargs["stdout"] is not subprocess.PIPE
    assert kwargs["stderr"] is not subprocess.PIPE
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


def test_wsl_file_capture_replaces_malformed_utf8_in_stderr(monkeypatch):
    def fake_run(command, **kwargs):
        kwargs["stderr"].write(b"bad:\x81tail")
        return subprocess.CompletedProcess(command, 9)

    monkeypatch.setattr(recover_cli.subprocess, "run", fake_run)

    returncode, stdout, stderr = recover_cli._run_wsl_file_capture(
        ["wsl.exe", "--fake"],
        {"format": "bodyrig-recovery-request", "version": 1, "sources": ["/tmp/a.mp4"]},
    )

    assert returncode == 9
    assert stdout == ""
    assert stderr == "bad:\ufffdtail"


def test_wsl_file_capture_does_not_wait_for_descendant_stdio_eof(tmp_path):
    child = tmp_path / "child.py"
    child.write_text(
        "import json, subprocess, sys\n"
        "json.load(sys.stdin)\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(4)'])\n"
        "sys.stdout.write('parent-exited')\n"
        "sys.stdout.flush()\n",
        encoding="utf-8",
    )

    started = time.monotonic()
    returncode, stdout, stderr = recover_cli._run_wsl_file_capture(
        [sys.executable, str(child)],
        {"hello": "world"},
    )
    elapsed = time.monotonic() - started

    assert returncode == 0
    assert stdout == "parent-exited"
    assert stderr == ""
    assert elapsed < 2.5


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
