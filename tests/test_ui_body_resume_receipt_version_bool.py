from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.ui_body_resume as ui_resume


RECONSTRUCTION_SHA = "a" * 64


def _plan() -> dict[str, object]:
    return {
        "recovery_mode": ui_resume.RESUME_FIT_ONLY,
        "package_already_complete": False,
        "package_sha256": None,
        "authority": {"reconstruction_sha256": RECONSTRUCTION_SHA},
    }


def _receipt(version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-interrupted-physical-fit-recovery",
        "version": version,
        "recovery_mode": ui_resume.RESUME_FIT_ONLY,
        "package_sha256": None,
        "production_activation": False,
        "human_visual_authority_required": True,
        "fitter_rerun": True,
        "adopted_complete_package": False,
        "reconstruction_authority_sha256": RECONSTRUCTION_SHA,
    }


def _write(path: Path, value: dict[str, object]) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def test_ui_resume_rejects_boolean_interrupted_recovery_receipt_version(tmp_path: Path) -> None:
    path = tmp_path / "interrupted-fit-recovery.json"
    _write(path, _receipt(True))

    with pytest.raises(ui_resume.UiJobError, match="receipt format/version mismatch"):
        ui_resume._verify_recovery_receipt(path, mode=ui_resume.RESUME_FIT_ONLY, plan=_plan())


def test_ui_resume_accepts_numeric_float_v1_without_expanding_authority(tmp_path: Path) -> None:
    path = tmp_path / "interrupted-fit-recovery.json"
    expected = _receipt(1.0)
    _write(path, expected)

    actual = ui_resume._verify_recovery_receipt(path, mode=ui_resume.RESUME_FIT_ONLY, plan=_plan())

    assert actual == expected
    assert actual["production_activation"] is False
    assert actual["human_visual_authority_required"] is True
    assert actual["fitter_rerun"] is True
    assert actual["adopted_complete_package"] is False
    assert actual["reconstruction_authority_sha256"] == RECONSTRUCTION_SHA
