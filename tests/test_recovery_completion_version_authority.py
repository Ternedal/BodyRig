from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.recover_cli as recover_cli


INVALID_V1_VALUES = (True, False, "1", None, 2)
VALID_V1_VALUES = (1, 1.0)


def _run_with_status_version(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: object,
) -> tuple[int, str, str, Path]:
    staging = tmp_path / "stage"
    staging.mkdir()
    monkeypatch.setattr(recover_cli.tempfile, "mkdtemp", lambda **kwargs: str(staging))

    class FakePopen:
        def __init__(self, command, **kwargs):
            status_path = Path(command[command.index("--status-file") + 1])
            status_path.write_text(
                json.dumps(
                    {
                        "format": "bodyrig-file-command-status",
                        "version": version,
                        "returncode": 9,
                    }
                ),
                encoding="utf-8",
            )

        def poll(self):
            return 0

    monkeypatch.setattr(recover_cli.subprocess, "Popen", FakePopen)

    return recover_cli._run_wsl_file_protocol(
        wsl_exe="wsl.exe",
        distribution="Ubuntu-22.04",
        external_python="/usr/bin/python3",
        target_command=["/usr/bin/python3", "/tmp/bridge.py"],
        request={"format": "bodyrig-recovery-request", "version": 1, "sources": ["/tmp/a.mp4"]},
        converter=lambda value: value,
    )


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_wsl_completion_status_rejects_noncanonical_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: object,
) -> None:
    with pytest.raises(recover_cli.RecoveryError, match="completion status is invalid"):
        _run_with_status_version(monkeypatch, tmp_path, version)

    assert (tmp_path / "stage" / "status.json").is_file()


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_wsl_completion_status_accepts_numeric_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: object,
) -> None:
    returncode, stdout, stderr, retained = _run_with_status_version(
        monkeypatch,
        tmp_path,
        version,
    )

    assert returncode == 9
    assert stdout == ""
    assert stderr == ""
    assert retained == tmp_path / "stage"
    assert retained.is_dir()
