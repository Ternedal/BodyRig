from __future__ import annotations

import json
import subprocess

import pytest

import bodyrig.wsl_tree_digest as digest


def test_digest_wsl_tree_returns_strict_tree_hash(monkeypatch):
    def fake_run(*, wsl_exe, distribution, command, timeout=7200):
        assert wsl_exe == "wsl.exe"
        assert distribution == "Ubuntu-22.04"
        assert command[0] == "/opt/sith/.venv/bin/python"
        assert command[-1] == "/opt/openpose/models"
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"sha256": "c" * 64, "file_count": 17, "byte_count": 123456789}),
            "",
        )

    monkeypatch.setattr(digest, "_run_wsl", fake_run)
    result = digest.digest_wsl_tree(
        distribution="Ubuntu-22.04",
        python="/opt/sith/.venv/bin/python",
        path="/opt/openpose/models",
    )
    assert result == {"sha256": "c" * 64, "file_count": 17, "byte_count": 123456789}


@pytest.mark.parametrize(
    "payload",
    [
        {"sha256": "C" * 64, "file_count": 1, "byte_count": 1},
        {"sha256": "c" * 64, "file_count": 0, "byte_count": 1},
        {"sha256": "c" * 64, "file_count": True, "byte_count": 1},
        {"sha256": "c" * 64, "file_count": 1, "byte_count": 0},
        {"sha256": "c" * 64, "file_count": 1, "byte_count": 1, "extra": 1},
    ],
)
def test_digest_wsl_tree_rejects_invalid_result(monkeypatch, payload):
    monkeypatch.setattr(
        digest,
        "_run_wsl",
        lambda **kwargs: subprocess.CompletedProcess(kwargs["command"], 0, json.dumps(payload), ""),
    )
    with pytest.raises(digest.WslTreeDigestError):
        digest.digest_wsl_tree(
            distribution="Ubuntu-22.04",
            python="/opt/sith/.venv/bin/python",
            path="/opt/openpose/models",
        )


def test_digest_wsl_tree_requires_absolute_linux_paths():
    with pytest.raises(digest.WslTreeDigestError, match="absolute Linux paths"):
        digest.digest_wsl_tree(
            distribution="Ubuntu-22.04",
            python="python",
            path="relative/models",
        )
