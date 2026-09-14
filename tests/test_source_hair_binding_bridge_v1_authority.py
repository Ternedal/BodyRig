from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

import sith_hair_review_runtime as bridge  # noqa: E402


AVATAR_SHA = "a" * 64
GEOMETRY = {"authority": "fixture"}


def _binding_value(version: object = 1) -> dict[str, object]:
    return {
        "format": bridge.BINDING_FORMAT,
        "version": version,
        "bodyId": "bodyid-fixture",
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


@pytest.mark.parametrize("version", (True, False, "1", None, 2))
def test_binding_rejects_boolean_or_non_numeric_v1(tmp_path: Path, version: object) -> None:
    path = tmp_path / "source-hair-body-binding.json"
    path.write_text(json.dumps(_binding_value(version)), encoding="utf-8")

    with pytest.raises(bridge.HairReviewRuntimeError, match="fields do not match v1"):
        bridge._binding(path, avatar_sha=AVATAR_SHA, geometry=GEOMETRY)


@pytest.mark.parametrize("version", (1, 1.0))
def test_binding_accepts_numeric_v1(tmp_path: Path, version: object) -> None:
    path = tmp_path / "source-hair-body-binding.json"
    path.write_text(json.dumps(_binding_value(version)), encoding="utf-8")

    parsed = bridge._binding(path, avatar_sha=AVATAR_SHA, geometry=GEOMETRY)
    assert parsed["version"] == version
    assert parsed["comparisonOnly"] is True
    assert parsed["humanReviewRequired"] is True
    assert parsed["productionActivation"] is False
