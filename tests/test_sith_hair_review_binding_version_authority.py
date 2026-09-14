from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest


BRIDGES = Path(__file__).resolve().parents[1] / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

import sith_hair_review_runtime as bridge  # noqa: E402


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)
GEOMETRY = {"authority": "exact-source-geometry-test"}
AVATAR_SHA = "a" * 64


def _binding(version: Any) -> dict[str, Any]:
    return {
        "format": bridge.BINDING_FORMAT,
        "version": version,
        "bodyId": "body-test",
        "packageSha256": "b" * 64,
        "avatarVrmSha256": AVATAR_SHA,
        "sourceGeometryAuthority": GEOMETRY,
        "hairCandidateReceiptSha256": "c" * 64,
        "hairObjSha256": "d" * 64,
        "hairMaterialSha256": "e" * 64,
        "hairTextureSha256": "f" * 64,
        "bindingStatus": "exact-source-and-donor-match",
        "runtimeIntegrationRequired": True,
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }


def _write_binding(tmp_path: Path, version: Any) -> Path:
    path = tmp_path / "source-hair-body-binding.json"
    path.write_text(json.dumps(_binding(version)), encoding="utf-8")
    return path


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_bridge_binding_rejects_boolean_non_numeric_and_wrong_v1(tmp_path: Path, version: Any) -> None:
    path = _write_binding(tmp_path, version)

    with pytest.raises(
        bridge.HairReviewRuntimeError,
        match="source hair body binding fields do not match v1",
    ):
        bridge._binding(path, avatar_sha=AVATAR_SHA, geometry=GEOMETRY)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_bridge_binding_preserves_numeric_v1_and_review_only_authority(tmp_path: Path, version: Any) -> None:
    path = _write_binding(tmp_path, version)

    value = bridge._binding(path, avatar_sha=AVATAR_SHA, geometry=GEOMETRY)

    assert value["version"] == version
    assert value["bindingStatus"] == "exact-source-and-donor-match"
    assert value["runtimeIntegrationRequired"] is True
    assert value["physicalSilhouetteReviewRequired"] is True
    assert value["comparisonOnly"] is True
    assert value["humanReviewRequired"] is True
    assert value["productionActivation"] is False
