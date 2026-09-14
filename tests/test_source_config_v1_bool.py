from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.identity_capture_cli import (
    IdentityCaptureConfigError,
    validate_identity_capture_config,
)
from bodyrig.observation import ObservationError
from bodyrig.observation_cli import _load_config


def identity_config(version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-identity-capture-config",
        "version": version,
        "adapter": "opencv-source-identity",
        "revision": "1",
        "command": ["python", "capture.py"],
        "timeout_seconds": 60,
    }


def observation_config(version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-observation-analyzer-config",
        "version": version,
        "adapter": "bodyrig-observation-test",
        "revision": "1",
        "command": ["python", "analyze.py"],
        "timeout_seconds": 60,
    }


@pytest.mark.parametrize("version", [1, 1.0])
def test_identity_capture_config_accepts_numeric_v1(version: object) -> None:
    result = validate_identity_capture_config(identity_config(version))
    assert result["version"] == version


@pytest.mark.parametrize("version", [True, False, "1", None, 2, 2.0])
def test_identity_capture_config_rejects_noncanonical_v1(version: object) -> None:
    with pytest.raises(IdentityCaptureConfigError, match="format/version"):
        validate_identity_capture_config(identity_config(version))


@pytest.mark.parametrize("version", [1, 1.0])
def test_observation_config_accepts_numeric_v1(tmp_path: Path, version: object) -> None:
    path = tmp_path / "observation-config.json"
    path.write_text(json.dumps(observation_config(version)), encoding="utf-8")
    result = _load_config(path)
    assert result["version"] == version


@pytest.mark.parametrize("version", [True, False, "1", None, 2, 2.0])
def test_observation_config_rejects_noncanonical_v1(tmp_path: Path, version: object) -> None:
    path = tmp_path / "observation-config.json"
    path.write_text(json.dumps(observation_config(version)), encoding="utf-8")
    with pytest.raises(ObservationError, match="format/version"):
        _load_config(path)


def test_source_config_hardening_preserves_other_validation() -> None:
    invalid_identity = identity_config(1)
    invalid_identity["timeout_seconds"] = True
    with pytest.raises(IdentityCaptureConfigError, match="timeout_seconds"):
        validate_identity_capture_config(invalid_identity)
