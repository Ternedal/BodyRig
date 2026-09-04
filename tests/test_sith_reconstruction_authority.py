from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.sith_reconstruction_authority import (
    AUTHORITY_FILENAME,
    SMPLX_FIT_PROFILE,
    SithReconstructionAuthorityError,
    validate_reconstruction_authority,
    write_reconstruction_authority,
)


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "workspace"
    stage = workspace / "sith-input-v1"
    stage.mkdir(parents=True)
    (stage / "reconstruction.json").write_text(
        json.dumps({"format": "bodyrig-sith-reconstruction", "version": 1}),
        encoding="utf-8",
    )
    return workspace


def test_authority_binds_reconstruction_bytes_gender_and_fit_profile(tmp_path: Path):
    workspace = _workspace(tmp_path)
    receipt = write_reconstruction_authority(workspace, body_model_gender="female")

    assert receipt["body_model_gender"] == "female"
    assert receipt["smplx_fit_profile"] == SMPLX_FIT_PROFILE
    assert len(receipt["reconstruction_sha256"]) == 64
    assert validate_reconstruction_authority(
        workspace,
        expected_body_model_gender="female",
    ) == receipt


def test_authority_rejects_legacy_workspace_without_receipt(tmp_path: Path):
    workspace = _workspace(tmp_path)

    with pytest.raises(SithReconstructionAuthorityError, match="legacy/incompatible"):
        validate_reconstruction_authority(
            workspace,
            expected_body_model_gender="female",
        )


def test_authority_rejects_gender_drift(tmp_path: Path):
    workspace = _workspace(tmp_path)
    write_reconstruction_authority(workspace, body_model_gender="male")

    with pytest.raises(SithReconstructionAuthorityError, match="gender does not match"):
        validate_reconstruction_authority(
            workspace,
            expected_body_model_gender="female",
        )


def test_authority_rejects_reconstruction_tamper(tmp_path: Path):
    workspace = _workspace(tmp_path)
    write_reconstruction_authority(workspace, body_model_gender="female")
    reconstruction = workspace / "sith-input-v1" / "reconstruction.json"
    reconstruction.write_text("{}\n", encoding="utf-8")

    with pytest.raises(SithReconstructionAuthorityError, match="changed after"):
        validate_reconstruction_authority(
            workspace,
            expected_body_model_gender="female",
        )


def test_authority_rejects_profile_drift(tmp_path: Path):
    workspace = _workspace(tmp_path)
    write_reconstruction_authority(workspace, body_model_gender="female")
    authority_path = workspace / "sith-input-v1" / AUTHORITY_FILENAME
    receipt = json.loads(authority_path.read_text(encoding="utf-8"))
    receipt["smplx_fit_profile"] = "legacy-precanonical-v0"
    authority_path.write_text(json.dumps(receipt), encoding="utf-8")

    with pytest.raises(SithReconstructionAuthorityError, match="profile is incompatible"):
        validate_reconstruction_authority(
            workspace,
            expected_body_model_gender="female",
        )
