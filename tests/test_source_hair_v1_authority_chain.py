from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import bodyrig.source_hair_review_runtime as review_runtime


BRIDGES = Path(__file__).resolve().parents[1] / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

import sith_hair_review_runtime as bridge_runtime  # noqa: E402


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64


def _bridge_result(version: object = 1) -> dict[str, object]:
    return {
        "format": review_runtime.BRIDGE_FORMAT,
        "version": version,
        "baseAvatarVrmSha256": SHA_A,
        "sourceHairBodyBindingSha256": SHA_B,
        "reviewVrmSha256": SHA_C,
        "targetModelFamily": "female",
        "skinIndex": 0,
        "hairMeshIndex": 1,
        "hairVertexCount": 120,
        "hairFaceCount": 80,
        "fitMax": 0.001,
        "fitRms": 0.0002,
        "nearestDonorDistanceP95": 0.01,
        "nearestDonorDistanceMax": 0.02,
        "bodyprintGeometryReplayApplied": False,
        "bodyprintMaxJointDelta": 0.0,
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "hairComponentAuthority": False,
        "productionActivation": False,
    }


def _metadata(version: object = 1) -> dict[str, object]:
    return {
        "format": review_runtime.METADATA_FORMAT,
        "version": version,
        "baseAvatarVrmSha256": SHA_A,
        "sourceHairBodyBindingSha256": SHA_B,
        "hairCandidateReceiptSha256": SHA_C,
        "hairObjSha256": SHA_D,
        "hairTextureSha256": SHA_E,
        "targetModelFamily": "female",
        "skinIndex": 0,
        "bodyprintGeometryReplayApplied": False,
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }


@pytest.mark.parametrize("invalid", [True, False, "1", None, {}, [], 2])
def test_review_bridge_rejects_non_numeric_v1(
    tmp_path: Path,
    invalid: object,
) -> None:
    path = tmp_path / "source-hair-review-bridge.json"
    value = _bridge_result(invalid)
    path.write_text(json.dumps(value), encoding="utf-8")

    with pytest.raises(
        review_runtime.SourceHairReviewRuntimeError,
        match="fields/format",
    ):
        review_runtime._bridge_result(path)


def test_review_bridge_preserves_numeric_float_v1(tmp_path: Path) -> None:
    path = tmp_path / "source-hair-review-bridge.json"
    path.write_text(json.dumps(_bridge_result(1.0)), encoding="utf-8")

    assert review_runtime._bridge_result(path)["version"] == 1.0


@pytest.mark.parametrize("invalid", [True, False, "1", None, {}, [], 2])
def test_runtime_metadata_rejects_non_numeric_v1(invalid: object) -> None:
    document = {
        "extras": {
            "bodyrig": {
                "hairReviewRuntime": _metadata(invalid),
            }
        }
    }

    with pytest.raises(
        review_runtime.SourceHairReviewRuntimeError,
        match="format/version",
    ):
        review_runtime._runtime_metadata(document)


def test_runtime_metadata_preserves_numeric_float_v1() -> None:
    document = {
        "extras": {
            "bodyrig": {
                "hairReviewRuntime": _metadata(1.0),
            }
        }
    }
    assert review_runtime._runtime_metadata(document)["version"] == 1.0


@pytest.mark.parametrize("invalid", [True, False, "1", None, {}, [], 2])
def test_finalize_binding_header_rejects_non_numeric_v1(invalid: object) -> None:
    value = {
        "format": review_runtime.BINDING_FORMAT,
        "version": invalid,
    }
    with pytest.raises(
        review_runtime.SourceHairReviewRuntimeError,
        match="binding format/version",
    ):
        review_runtime._validate_persisted_binding_version(value)


def test_finalize_binding_header_preserves_numeric_float_v1() -> None:
    review_runtime._validate_persisted_binding_version(
        {
            "format": review_runtime.BINDING_FORMAT,
            "version": 1.0,
        }
    )


def _bridge_binding(
    geometry: dict[str, object],
    *,
    version: object = 1,
) -> dict[str, object]:
    return {
        "format": bridge_runtime.BINDING_FORMAT,
        "version": version,
        "bodyId": "body-test",
        "packageSha256": SHA_A,
        "avatarVrmSha256": SHA_B,
        "sourceGeometryAuthority": geometry,
        "hairCandidateReceiptSha256": SHA_C,
        "hairObjSha256": SHA_D,
        "hairMaterialSha256": SHA_E,
        "hairTextureSha256": SHA_F,
        "bindingStatus": "exact-source-and-donor-match",
        "runtimeIntegrationRequired": True,
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }


@pytest.mark.parametrize("invalid", [True, False, "1", None, {}, [], 2])
def test_bridge_binding_readback_rejects_non_numeric_v1(
    tmp_path: Path,
    invalid: object,
) -> None:
    geometry = {"authority": "fixture"}
    path = tmp_path / "source-hair-body-binding.json"
    path.write_text(
        json.dumps(_bridge_binding(geometry, version=invalid)),
        encoding="utf-8",
    )

    with pytest.raises(
        bridge_runtime.HairReviewRuntimeError,
        match="fields do not match v1",
    ):
        bridge_runtime._binding(
            path,
            avatar_sha=SHA_B,
            geometry=geometry,
        )


def test_bridge_binding_readback_preserves_numeric_float_v1(
    tmp_path: Path,
) -> None:
    geometry = {"authority": "fixture"}
    path = tmp_path / "source-hair-body-binding.json"
    path.write_text(
        json.dumps(_bridge_binding(geometry, version=1.0)),
        encoding="utf-8",
    )

    assert bridge_runtime._binding(
        path,
        avatar_sha=SHA_B,
        geometry=geometry,
    )["version"] == 1.0
