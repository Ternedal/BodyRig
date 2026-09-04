from __future__ import annotations

import json
import subprocess

import pytest

import bodyrig.wsl_file_digest as digest


def test_digest_wsl_file_returns_strict_hash_and_size(monkeypatch):
    def fake_run(*, wsl_exe, distribution, command, timeout=3600):
        assert wsl_exe == "wsl.exe"
        assert distribution == "Ubuntu-22.04"
        assert command[0] == "/opt/sith/.venv/bin/python"
        assert command[-1] == "/opt/openpose/build/examples/openpose/openpose.bin"
        return subprocess.CompletedProcess(command, 0, json.dumps({"sha256": "a" * 64, "byte_count": 12345}), "")

    monkeypatch.setattr(digest, "_run_wsl", fake_run)
    result = digest.digest_wsl_file(
        distribution="Ubuntu-22.04",
        python="/opt/sith/.venv/bin/python",
        path="/opt/openpose/build/examples/openpose/openpose.bin",
    )
    assert result == {"sha256": "a" * 64, "byte_count": 12345}


@pytest.mark.parametrize(
    "payload",
    [
        {"sha256": "A" * 64, "byte_count": 1},
        {"sha256": "a" * 64, "byte_count": 0},
        {"sha256": "a" * 64, "byte_count": True},
        {"sha256": "a" * 64, "byte_count": 1, "extra": 1},
    ],
)
def test_digest_wsl_file_rejects_invalid_result(monkeypatch, payload):
    monkeypatch.setattr(
        digest,
        "_run_wsl",
        lambda **kwargs: subprocess.CompletedProcess(kwargs["command"], 0, json.dumps(payload), ""),
    )
    with pytest.raises(digest.WslFileDigestError):
        digest.digest_wsl_file(
            distribution="Ubuntu-22.04",
            python="/opt/sith/.venv/bin/python",
            path="/opt/openpose/build/examples/openpose/openpose.bin",
        )


def test_digest_wsl_file_requires_absolute_linux_paths():
    with pytest.raises(digest.WslFileDigestError, match="absolute Linux paths"):
        digest.digest_wsl_file(
            distribution="Ubuntu-22.04",
            python="python",
            path="relative/openpose.bin",
        )
