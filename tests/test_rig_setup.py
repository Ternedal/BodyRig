from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.bridges.hmr2_config import FOUR_D_HUMANS_REVISION, PHALP_REVISION
from bodyrig.rig_setup import RigSetupError, load_rig_setup
from bodyrig.sith_preflight import OPENPOSE_REVISION, SITH_REVISION


def _write(path: Path, value: dict) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path) -> Path:
    summary = tmp_path / "recovery-environment.json"
    preflight = tmp_path / "recovery-preflight.json"
    sith = tmp_path / "sith-setup.json"
    external_python = str(tmp_path / "recovery-python.exe")
    fourd = str(tmp_path / "4D-Humans")
    phalp = str(tmp_path / "PHALP")
    summary_sha = _write(summary, {
        "format": "bodyrig-recovery-environment",
        "version": 1,
        "root": str(tmp_path),
        "external_python": external_python,
        "four_d_humans_repo": fourd,
        "four_d_humans_revision": FOUR_D_HUMANS_REVISION,
        "phalp_repo": phalp,
        "phalp_revision": PHALP_REVISION,
        "smpl_expected_path": str(tmp_path / "neutral.pkl"),
        "smpl_present": True,
    })
    preflight_sha = _write(preflight, {"format": "bodyrig-recovery-preflight", "version": 1, "ok": True})
    sith_sha = _write(sith, {
        "format": "bodyrig-sith-setup",
        "version": 3,
        "distribution": "Ubuntu-22.04",
        "sith": {"repository": "/opt/sith", "revision": SITH_REVISION, "python": "/opt/sith/.venv/bin/python"},
        "openpose": {
            "repository": "/opt/openpose",
            "revision": OPENPOSE_REVISION,
            "executable": "/opt/openpose/build/examples/openpose/openpose.bin",
            "sha256": "b" * 64,
            "byte_count": 987654,
            "models_sha256": "c" * 64,
            "models_file_count": 17,
            "models_byte_count": 456789012,
        },
        "diffusion_model": {"path": "/opt/models/sith", "sha256": "a" * 64, "file_count": 5, "byte_count": 1234},
    })
    rig = tmp_path / "rig.json"
    _write(rig, {
        "format": "bodyrig-rig-setup",
        "version": 1,
        "recovery": {
            "environment_summary": str(summary),
            "environment_summary_sha256": summary_sha,
            "preflight": str(preflight),
            "preflight_sha256": preflight_sha,
            "external_python": external_python,
            "four_d_humans_repo": fourd,
            "phalp_repo": phalp,
        },
        "high_fidelity": {"setup_report": str(sith), "setup_report_sha256": sith_sha},
    })
    return rig


def test_full_rig_setup_verifies_nested_evidence(tmp_path: Path):
    rig = _fixture(tmp_path)
    value = load_rig_setup(rig)
    assert value["format"] == "bodyrig-rig-setup"


def test_full_rig_setup_rejects_nested_tamper(tmp_path: Path):
    rig = _fixture(tmp_path)
    value = json.loads(rig.read_text(encoding="utf-8"))
    summary = Path(value["recovery"]["environment_summary"])
    summary.write_text(summary.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(RigSetupError, match="environment summary SHA-256 mismatch"):
        load_rig_setup(rig)


def test_full_rig_setup_rejects_wrong_recovery_revision_even_with_rehashed_summary(tmp_path: Path):
    rig = _fixture(tmp_path)
    value = json.loads(rig.read_text(encoding="utf-8"))
    summary = Path(value["recovery"]["environment_summary"])
    summary_value = json.loads(summary.read_text(encoding="utf-8"))
    summary_value["four_d_humans_revision"] = "0" * 40
    summary.write_text(json.dumps(summary_value), encoding="utf-8")
    value["recovery"]["environment_summary_sha256"] = hashlib.sha256(summary.read_bytes()).hexdigest()
    rig.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RigSetupError, match="4D-Humans revision mismatch"):
        load_rig_setup(rig)
