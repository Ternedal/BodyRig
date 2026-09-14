from __future__ import annotations

from typing import Any

import pytest

from bodyrig import source_hair_eye_preview_runtime as preview


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)


def _source_receipt(version: Any) -> dict[str, Any]:
    return {
        "format": preview.SOURCE_FORMAT,
        "version": version,
        "bodyrigRevision": "a" * 40,
        "bridgeScriptSha256": "b" * 64,
        "bodyId": "bodyid-test",
        "packageSha256": "c" * 64,
        "baseAvatarVrmSha256": "d" * 64,
        "sourceHairBodyBindingSha256": "e" * 64,
        "hairCandidateReceiptSha256": "f" * 64,
        "eyeComponentReceiptSha256": "1" * 64,
        "eyeAppearanceReceiptSha256": "2" * 64,
        "reviewVrmSha256": "3" * 64,
        "bridgeResultSha256": "4" * 64,
        "targetModelFamily": "female",
        "hairMeshIndex": 1,
        "eyeMeshIndex": 2,
        "leftEyeFaceCount": 12,
        "rightEyeFaceCount": 13,
        "sourceHairRuntimeApplied": True,
        "sourceEyeSurfaceApplied": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "runtime-applied",
        "eyelashStatus": "missing",
        "runtimeIntegrationStatus": "hair-and-eyes-review-artifact-ready",
        "physicalSilhouetteReviewRequired": True,
        "physicalFaceCloseupReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "hairComponentAuthority": False,
        "eyeComponentAuthority": False,
        "productionActivation": False,
    }


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_python_preview_rejects_boolean_non_numeric_and_wrong_source_v1(version: Any) -> None:
    receipt = _source_receipt(version)

    with pytest.raises(
        preview.SourceHairEyePreviewRuntimeError,
        match="source hair\\+eye review receipt fields/format do not match v1",
    ):
        preview._validate_source_receipt(receipt)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_python_preview_preserves_numeric_v1_and_review_only_authority(version: Any) -> None:
    receipt = _source_receipt(version)

    preview._validate_source_receipt(receipt)

    assert receipt["version"] == version
    assert receipt["sourceHairRuntimeApplied"] is True
    assert receipt["sourceEyeSurfaceApplied"] is True
    assert receipt["comparisonOnly"] is True
    assert receipt["humanReviewRequired"] is True
    assert receipt["hairComponentAuthority"] is False
    assert receipt["eyeComponentAuthority"] is False
    assert receipt["productionActivation"] is False
