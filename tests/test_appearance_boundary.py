from __future__ import annotations

import pytest

from bodyrig.appearance_boundary import (
    ADAPTER,
    REVISION,
    STAGE,
    AppearanceBoundaryError,
    provenance_stage,
    validate_pipeline,
)
from bodyrig.external_fitter_cli import (
    ExternalFitterConfigError,
    validate_external_fitter_config,
)


def test_canonical_appearance_boundary_is_exact_and_machine_readable():
    stage = provenance_stage()
    assert stage == {
        "stage": STAGE,
        "adapter": ADAPTER,
        "revision": REVISION,
    }
    assert validate_pipeline([stage]) is True


def test_appearance_boundary_rejects_missing_duplicate_or_drifted_policy():
    with pytest.raises(AppearanceBoundaryError, match="missing"):
        validate_pipeline([])
    with pytest.raises(AppearanceBoundaryError, match="exactly one"):
        validate_pipeline([provenance_stage(), provenance_stage()])
    with pytest.raises(AppearanceBoundaryError, match="non-canonical"):
        validate_pipeline([
            {"stage": STAGE, "adapter": ADAPTER, "revision": "outfit-baked-v1"}
        ])


def test_external_fitter_config_forbids_clothing_as_body_capability():
    config = {
        "format": "bodyrig-external-fitter-config",
        "version": 1,
        "adapter": "fixture",
        "revision": "1",
        "command": ["fixture"],
        "capabilities": {
            "visual_identity": True,
            "textures": True,
            "hair": False,
            "clothing": True,
        },
        "timeout_seconds": 30,
    }
    with pytest.raises(ExternalFitterConfigError, match="garments/outfits are external"):
        validate_external_fitter_config(config)

    config["capabilities"]["clothing"] = False
    assert validate_external_fitter_config(config) == config
