from __future__ import annotations

import json
import subprocess

import pytest

import bodyrig.sith_model as model


def test_digest_model_tree_accepts_strict_result(monkeypatch):
    seen = {}

    def fake_run(*, wsl_exe, distribution, command, timeout=7200):
        seen["wsl_exe"] = wsl_exe
        seen["distribution"] = distribution
        seen["command"] = list(command)
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps({"sha256": "a" * 64, "file_count": 42, "byte_count": 123456}),
            "",
        )

    monkeypatch.setattr(model, "_run_wsl", fake_run)
    result = model.digest_model_tree(
        distribution="Ubuntu-22.04",
        python="/opt/sith/.venv/bin/python",
        model_path="/opt/models/sith-diffusion",
    )

    assert result == {"sha256": "a" * 64, "file_count": 42, "byte_count": 123456}
    assert seen["wsl_exe"] == "wsl.exe"
    assert seen["distribution"] == "Ubuntu-22.04"
    assert seen["command"][0:2] == ["/opt/sith/.venv/bin/python", "-c"]
    assert seen["command"][-1] == "/opt/models/sith-diffusion"


def test_digest_model_tree_rejects_bad_digest_and_paths(monkeypatch):
    monkeypatch.setattr(
        model,
        "_run_wsl",
        lambda **kwargs: subprocess.CompletedProcess(
            kwargs["command"], 0, json.dumps({"sha256": "bad", "file_count": 1, "byte_count": 1}), ""
        ),
    )
    with pytest.raises(model.SithModelError, match="digest is invalid"):
        model.digest_model_tree(
            distribution="Ubuntu-22.04",
            python="/opt/sith/python",
            model_path="/opt/model",
        )

    with pytest.raises(model.SithModelError, match="absolute Linux"):
        model.digest_model_tree(
            distribution="Ubuntu-22.04",
            python="python",
            model_path="/opt/model",
        )


def test_digest_model_tree_fails_closed_on_process_error(monkeypatch):
    monkeypatch.setattr(
        model,
        "_run_wsl",
        lambda **kwargs: subprocess.CompletedProcess(kwargs["command"], 7, "", "no model"),
    )
    with pytest.raises(model.SithModelError, match="digest failed"):
        model.digest_model_tree(
            distribution="Ubuntu-22.04",
            python="/opt/sith/python",
            model_path="/opt/model",
        )
