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


def _payload():
    return {
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


def test_wsl_recovery_uses_in_wsl_file_protocol_and_no_windows_output_handles(monkeypatch, tmp_path):
    conversions = []
    staging = tmp_path / "stage"
    staging.mkdir()
    monkeypatch.setattr(recover_cli.tempfile, "mkdtemp", lambda **kwargs: str(staging))

    def fake_converter(value: str) -> str:
        conversions.append(value)
        return value

    monkeypatch.setattr(
        recover_cli,
        "make_wsl_path_converter",
        lambda wsl_exe, distribution: fake_converter,
    )

    calls = []

    class FakePopen:
        def __init__(self, command, **kwargs):
            calls.append((list(command), dict(kwargs)))
            self.command = list(command)
            request_path = Path(self.command[self.command.index("--stdin-file") + 1])
            stdout_path = Path(self.command[self.command.index("--stdout-file") + 1])
            stderr_path = Path(self.command[self.command.index("--stderr-file") + 1])
            status_path = Path(self.command[self.command.index("--status-file") + 1])
            request = json.loads(request_path.read_text(encoding="utf-8"))
            assert request == {
                "format": "bodyrig-recovery-request",
                "version": 1,
                "sources": [str(Path(r"C:\BodyRig\segment-01.mp4"))],
            }
            stdout_path.write_text(json.dumps(_payload()), encoding="utf-8")
            stderr_path.write_bytes(b"diagnostic \x81 byte")
            status_path.write_text(
                json.dumps(
                    {
                        "format": "bodyrig-file-command-status",
                        "version": 1,
                        "returncode": 0,
                    }
                ),
                encoding="utf-8",
            )

        def poll(self):
            return 0

    monkeypatch.setattr(recover_cli.subprocess, "Popen", FakePopen)

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
    assert kwargs == {"stdin": subprocess.DEVNULL}
    assert command[:5] == [
        r"C:\Windows\System32\wsl.exe",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/home/anders/.local/share/bodyrig/recovery/venv/bin/python",
    ]
    assert "file_command_bridge.py" in command[5]
    second_separator = command.index("--", 5)
    target = command[second_separator + 1 :]
    assert target == [
        "/home/anders/.local/share/bodyrig/recovery/venv/bin/python",
        str(recover_cli.bridge_script_path().resolve()),
        "--repo",
        "/home/anders/.local/share/bodyrig/recovery/4D-Humans",
        "--phalp-repo",
        "/home/anders/.local/share/bodyrig/recovery/PHALP",
    ]
    assert not staging.exists()
    assert any(value.endswith("file_command_bridge.py") for value in conversions)
    assert any(value.endswith("request.json") for value in conversions)
    assert any(value.endswith("status.json") for value in conversions)


def test_wsl_file_protocol_replaces_malformed_utf8_and_retains_failure_staging(monkeypatch, tmp_path):
    staging = tmp_path / "failure-stage"
    staging.mkdir()
    monkeypatch.setattr(recover_cli.tempfile, "mkdtemp", lambda **kwargs: str(staging))

    class FakePopen:
        def __init__(self, command, **kwargs):
            stdout_path = Path(command[command.index("--stdout-file") + 1])
            stderr_path = Path(command[command.index("--stderr-file") + 1])
            status_path = Path(command[command.index("--status-file") + 1])
            stdout_path.write_bytes(b"")
            stderr_path.write_bytes(b"bad:\x81tail")
            status_path.write_text(
                json.dumps(
                    {
                        "format": "bodyrig-file-command-status",
                        "version": 1,
                        "returncode": 9,
                    }
                ),
                encoding="utf-8",
            )

        def poll(self):
            return 0

    monkeypatch.setattr(recover_cli.subprocess, "Popen", FakePopen)

    returncode, stdout, stderr, retained = recover_cli._run_wsl_file_protocol(
        wsl_exe="wsl.exe",
        distribution="Ubuntu-22.04",
        external_python="/usr/bin/python3",
        target_command=["/usr/bin/python3", "/tmp/bridge.py"],
        request={"format": "bodyrig-recovery-request", "version": 1, "sources": ["/tmp/a.mp4"]},
        converter=lambda value: value,
    )

    assert returncode == 9
    assert stdout == ""
    assert stderr == "bad:\ufffdtail"
    assert retained == staging
    assert staging.is_dir()
    assert (staging / "status.json").is_file()


def test_wsl_file_protocol_rejects_transport_exit_without_status(monkeypatch, tmp_path):
    staging = tmp_path / "missing-status"
    staging.mkdir()
    monkeypatch.setattr(recover_cli.tempfile, "mkdtemp", lambda **kwargs: str(staging))
    monkeypatch.setattr(recover_cli.time, "sleep", lambda seconds: None)

    class FakePopen:
        def __init__(self, command, **kwargs):
            self.command = command

        def poll(self):
            return 17

    monkeypatch.setattr(recover_cli.subprocess, "Popen", FakePopen)

    with pytest.raises(Exception, match="without an authoritative completion status"):
        recover_cli._run_wsl_file_protocol(
            wsl_exe="wsl.exe",
            distribution="Ubuntu-22.04",
            external_python="/usr/bin/python3",
            target_command=["/usr/bin/python3", "/tmp/bridge.py"],
            request={"format": "bodyrig-recovery-request", "version": 1, "sources": ["/tmp/a.mp4"]},
            converter=lambda value: value,
        )
    assert staging.is_dir()


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
