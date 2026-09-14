from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from bodyrig import source_hair_review_runtime as runtime


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)


def _bridge_value(version: Any) -> dict[str, Any]:
    return {
        "format": runtime.BRIDGE_FORMAT,
        "version": version,
        "baseAvatarVrmSha256": "a" * 64,
        "sourceHairBodyBindingSha256": "b" * 64,
        "reviewVrmSha256": "c" * 64,
        "targetModelFamily": "female",
        "skinIndex": 0,
        "hairMeshIndex": 1,
        "hairVertexCount": 3,
        "hairFaceCount": 1,
        "fitMax": 0.001,
        "fitRms": 0.0005,
        "nearestDonorDistanceP95": 0.001,
        "nearestDonorDistanceMax": 0.002,
        "bodyprintGeometryReplayApplied": True,
        "bodyprintMaxJointDelta": 0.001,
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "hairComponentAuthority": False,
        "productionActivation": False,
    }


def _runtime_document(version: Any) -> dict[str, Any]:
    return {
        "extras": {
            "bodyrig": {
                "hairReviewRuntime": {
                    "format": runtime.METADATA_FORMAT,
                    "version": version,
                    "baseAvatarVrmSha256": "a" * 64,
                    "sourceHairBodyBindingSha256": "b" * 64,
                    "hairCandidateReceiptSha256": "c" * 64,
                    "hairObjSha256": "d" * 64,
                    "hairTextureSha256": "e" * 64,
                    "targetModelFamily": "female",
                    "skinIndex": 0,
                    "bodyprintGeometryReplayApplied": True,
                    "physicalSilhouetteReviewRequired": True,
                    "comparisonOnly": True,
                    "humanReviewRequired": True,
                    "productionActivation": False,
                }
            }
        }
    }


def _write_bridge(path: Path, version: Any) -> None:
    path.write_text(json.dumps(_bridge_value(version), sort_keys=True), encoding="utf-8")


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_bridge_result_rejects_boolean_non_numeric_and_wrong_v1(tmp_path: Path, version: Any) -> None:
    path = tmp_path / "source-hair-review-bridge.json"
    _write_bridge(path, version)

    with pytest.raises(runtime.SourceHairReviewRuntimeError, match="fields/format do not match v1"):
        runtime._bridge_result(path)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_bridge_result_preserves_numeric_v1_compatibility(tmp_path: Path, version: Any) -> None:
    path = tmp_path / "source-hair-review-bridge.json"
    _write_bridge(path, version)

    value = runtime._bridge_result(path)

    assert value["version"] == version
    assert value["comparisonOnly"] is True
    assert value["humanReviewRequired"] is True
    assert value["hairComponentAuthority"] is False
    assert value["productionActivation"] is False


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_runtime_metadata_rejects_boolean_non_numeric_and_wrong_v1(version: Any) -> None:
    with pytest.raises(runtime.SourceHairReviewRuntimeError, match="runtime metadata format/version mismatch"):
        runtime._runtime_metadata(_runtime_document(version))


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_runtime_metadata_preserves_numeric_v1_compatibility(version: Any) -> None:
    value = runtime._runtime_metadata(_runtime_document(version))

    assert value["version"] == version
    assert value["comparisonOnly"] is True
    assert value["humanReviewRequired"] is True
    assert value["productionActivation"] is False
