from __future__ import annotations

import pytest

from bodyrig.external_fitter_cli import (
    ExternalFitterConfigError,
    validate_external_fitter_config,
)


def config(version: object) -> dict:
    return {
        "format": "bodyrig-external-fitter-config",
        "version": version,
        "adapter": "sith-smplx-vrm",
        "revision": "1",
        "command": ["python", "-m", "bodyrig.sith_fitter_orchestrator"],
        "capabilities": {
            "visual_identity": True,
            "textures": True,
            "hair": False,
            "clothing": False,
        },
        "timeout_seconds": 3600,
    }


@pytest.mark.parametrize("version", [1, 1.0])
def test_external_fitter_config_accepts_numeric_v1(version: object) -> None:
    value = config(version)
    assert validate_external_fitter_config(value) == value


@pytest.mark.parametrize("version", [True, False, "1", None, 0, 2])
def test_external_fitter_config_rejects_non_numeric_or_non_v1(version: object) -> None:
    with pytest.raises(ExternalFitterConfigError, match="format/version"):
        validate_external_fitter_config(config(version))
