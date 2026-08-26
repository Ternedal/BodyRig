from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.sith_preflight import OPENPOSE_REVISION, SITH_REVISION
from bodyrig.sith_setup import SithSetupError, load_setup_report, validate_setup_report


def _report() -> dict:
    repo = "/home/test/.local/share/bodyrig/sith"
    return {
        "format": "bodyrig-sith-setup",
        "version": 4,
        "distribution": "Ubuntu-22.04",
        "sith": {
            "repository": repo,
            "revision": SITH_REVISION,
            "python": f"{repo}/.bodyrig-venv/bin/python",
        },
        "openpose": {
            "repository": "/home/test/.local/share/bodyrig/openpose",
            "revision": OPENPOSE_REVISION,
            "executable": "/home/test/.local/share/bodyrig/openpose/build/examples/openpose/openpose.bin",
            "sha256": "b" * 64,
            "byte_count": 987654,
            "models_sha256": "c" * 64,
            "models_file_count": 17,
            "models_byte_count": 456789012,
        },
        "checkpoints": {
            "recon_model": {
                "path": f"{repo}/checkpoints/recon_model.pth",
                "sha256": "d" * 64,
                "byte_count": 785432109,
            },
            "smplerx": {
                "path": f"{repo}/checkpoints/save_smplerx.pth",
                "sha256": "e" * 64,
                "byte_count": 2654321098,
            },
        },
        "diffusion_model": {
            "path": "/home/test/.cache/bodyrig/sith-diffusion",
            "sha256": "a" * 64,
            "file_count": 42,
            "byte_count": 123456,
        },
    }


def test_setup_report_roundtrip(tmp_path: Path):
    path = tmp_path / "setup.json"
    path.write_text(json.dumps(_report()), encoding="utf-8")
    value = load_setup_report(path)
    assert value["sith"]["revision"] == SITH_REVISION
    assert value["openpose"]["revision"] == OPENPOSE_REVISION
    assert value["openpose"]["sha256"] == "b" * 64
    assert value["openpose"]["byte_count"] == 987654
    assert value["openpose"]["models_sha256"] == "c" * 64
    assert value["openpose"]["models_file_count"] == 17
    assert value["openpose"]["models_byte_count"] == 456789012
    assert value["checkpoints"]["recon_model"]["sha256"] == "d" * 64
    assert value["checkpoints"]["recon_model"]["byte_count"] == 785432109
    assert value["checkpoints"]["smplerx"]["sha256"] == "e" * 64
    assert value["checkpoints"]["smplerx"]["byte_count"] == 2654321098
    assert value["diffusion_model"]["sha256"] == "a" * 64


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(extra=True), "fields must match"),
        (lambda value: value.update(version=3), "unsupported SiTH setup report"),
        (lambda value: value["sith"].update(revision="deadbeef"), "pinned revision"),
        (lambda value: value["openpose"].update(revision="deadbeef"), "OpenPose setup revision"),
        (lambda value: value["openpose"].update(sha256="B" * 64), "openpose.sha256"),
        (lambda value: value["openpose"].update(byte_count=0), "openpose.byte_count"),
        (lambda value: value["openpose"].update(models_sha256="C" * 64), "openpose.models_sha256"),
        (lambda value: value["openpose"].update(models_file_count=0), "openpose.models_file_count"),
        (lambda value: value["openpose"].update(models_byte_count=0), "openpose.models_byte_count"),
        (lambda value: value["checkpoints"]["recon_model"].update(sha256="D" * 64), "checkpoints.recon_model.sha256"),
        (lambda value: value["checkpoints"]["smplerx"].update(byte_count=0), "checkpoints.smplerx.byte_count"),
        (
            lambda value: value["checkpoints"]["recon_model"].update(path="/tmp/recon_model.pth"),
            "pinned SiTH checkpoint path",
        ),
        (
            lambda value: value["checkpoints"]["smplerx"].update(path="/tmp/save_smplerx.pth"),
            "pinned SiTH checkpoint path",
        ),
        (lambda value: value["diffusion_model"].update(sha256="A" * 64), "lowercase SHA-256"),
        (lambda value: value["sith"].update(repository="relative/path"), "absolute Linux path"),
    ],
)
def test_setup_report_rejects_drift(mutate, message):
    value = _report()
    mutate(value)
    with pytest.raises(SithSetupError, match=message):
        validate_setup_report(value)
