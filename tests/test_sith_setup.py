from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.sith_preflight import OPENPOSE_REVISION, SITH_REVISION
from bodyrig.sith_setup import SithSetupError, load_setup_report, validate_setup_report


def _report() -> dict:
    return {
        "format": "bodyrig-sith-setup",
        "version": 2,
        "distribution": "Ubuntu-22.04",
        "sith": {
            "repository": "/home/test/.local/share/bodyrig/sith",
            "revision": SITH_REVISION,
            "python": "/home/test/.local/share/bodyrig/sith/.bodyrig-venv/bin/python",
        },
        "openpose": {
            "repository": "/home/test/.local/share/bodyrig/openpose",
            "revision": OPENPOSE_REVISION,
            "executable": "/home/test/.local/share/bodyrig/openpose/build/examples/openpose/openpose.bin",
            "sha256": "b" * 64,
            "byte_count": 987654,
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
    assert value["diffusion_model"]["sha256"] == "a" * 64


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda value: value.update(extra=True), "fields must match"),
        (lambda value: value.update(version=1), "unsupported SiTH setup report"),
        (lambda value: value["sith"].update(revision="deadbeef"), "pinned revision"),
        (lambda value: value["openpose"].update(revision="deadbeef"), "OpenPose setup revision"),
        (lambda value: value["openpose"].update(sha256="B" * 64), "openpose.sha256"),
        (lambda value: value["openpose"].update(byte_count=0), "openpose.byte_count"),
        (lambda value: value["diffusion_model"].update(sha256="A" * 64), "lowercase SHA-256"),
        (lambda value: value["sith"].update(repository="relative/path"), "absolute Linux path"),
    ],
)
def test_setup_report_rejects_drift(mutate, message):
    value = _report()
    mutate(value)
    with pytest.raises(SithSetupError, match=message):
        validate_setup_report(value)
