from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.source_hair_eye_review_runtime as runtime


INVALID_V1_VALUES = (True, False, "1", None, 2)
VALID_V1_VALUES = (1, 1.0)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bridge_value(version: object) -> dict[str, object]:
    return {
        "format": "bodyrig-source-hair-eye-review-bridge",
        "version": version,
        "baseAvatarVrmSha256": "a" * 64,
        "sourceHairBodyBindingSha256": "b" * 64,
        "hairReviewBridgeSha256": "c" * 64,
        "hairMeshIndex": 1,
        "eyeMeshIndex": 2,
        "reviewVrmSha256": "d" * 64,
        "targetModelFamily": "female",
        "leftEyeFaceCount": 12,
        "rightEyeFaceCount": 13,
        "leftEyeRuntimeVertices": 20,
        "rightEyeRuntimeVertices": 21,
        "sourceHairRuntimeApplied": True,
        "sourceEyeSurfaceApplied": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "runtime-applied",
        "eyelashStatus": "missing",
        "physicalSilhouetteReviewRequired": True,
        "physicalFaceCloseupReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "hairComponentAuthority": False,
        "eyeComponentAuthority": False,
        "productionActivation": False,
    }


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_bridge_rejects_noncanonical_v1(tmp_path: Path, version: object) -> None:
    path = tmp_path / "bridge.json"
    path.write_text(json.dumps(_bridge_value(version)), encoding="utf-8")

    with pytest.raises(runtime.SourceHairEyeReviewRuntimeError, match="fields/format"):
        runtime._bridge(path)


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_bridge_accepts_numeric_v1(tmp_path: Path, version: object) -> None:
    path = tmp_path / "bridge.json"
    path.write_text(json.dumps(_bridge_value(version)), encoding="utf-8")

    assert runtime._bridge(path)["version"] == 1


def _prepare_eye_receipts(
    tmp_path: Path,
    *,
    component_version: object = 1,
    appearance_version: object = 1,
) -> tuple[Path, Path, dict[str, str]]:
    geometry_dir = tmp_path / "eyes"
    appearance_dir = tmp_path / "appearance"
    geometry_dir.mkdir()
    appearance_dir.mkdir()

    left_obj = b"v 0 0 0\nf 1 1 1\n"
    right_obj = b"v 0 0 0\nf 1 1 1\n"
    bake = b"\x89PNG\r\n\x1a\ncanonical-eye"
    left_png = b"\x89PNG\r\n\x1a\nleft"
    right_png = b"\x89PNG\r\n\x1a\nright"
    (geometry_dir / "left_eye.obj").write_bytes(left_obj)
    (geometry_dir / "right_eye.obj").write_bytes(right_obj)
    (appearance_dir / "canonical_eye_source_bake.png").write_bytes(bake)
    (appearance_dir / "left_eye_appearance.png").write_bytes(left_png)
    (appearance_dir / "right_eye_appearance.png").write_bytes(right_png)

    body_geometry = {
        "bodyModelGender": "female",
        "fittedDonorObjSha256": "1" * 64,
        "reconstructionSha256": "2" * 64,
        "sourceMeshSha256": "3" * 64,
        "sourceTextureSha256": "4" * 64,
    }
    component = {
        "format": "bodyrig-eye-component-candidate",
        "version": component_version,
        "targetModelFamily": "female",
        "donorObjSha256": "1" * 64,
        "leftEyeObjSha256": _sha(left_obj),
        "rightEyeObjSha256": _sha(right_obj),
        "leftEyeFaceCount": 12,
        "rightEyeFaceCount": 13,
        "leftEyeJointIndex": 23,
        "rightEyeJointIndex": 24,
        "explicitEyeGeometry": True,
        "componentStatus": "partial",
        "productionReady": False,
    }
    appearance = {
        "format": "bodyrig-eye-appearance-candidate",
        "version": appearance_version,
        "targetModelFamily": "female",
        "donorObjSha256": "1" * 64,
        "sourceReconstructionSha256": "2" * 64,
        "sourceMeshSha256": "3" * 64,
        "sourceTextureSha256": "4" * 64,
        "canonicalBakeSha256": _sha(bake),
        "leftEyeAppearancePngSha256": _sha(left_png),
        "rightEyeAppearancePngSha256": _sha(right_png),
        "leftEyeFaceCount": 12,
        "rightEyeFaceCount": 13,
        "sourceDerivedEyeSurfaceAppearance": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "componentStatus": "partial",
        "productionReady": False,
    }
    (geometry_dir / "eye-component-candidate.json").write_text(
        json.dumps(component), encoding="utf-8"
    )
    (appearance_dir / "eye-appearance-candidate.json").write_text(
        json.dumps(appearance), encoding="utf-8"
    )
    return geometry_dir, appearance_dir, body_geometry


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_eye_component_rejects_noncanonical_v1(tmp_path: Path, version: object) -> None:
    geometry_dir, appearance_dir, body_geometry = _prepare_eye_receipts(
        tmp_path,
        component_version=version,
    )

    with pytest.raises(runtime.SourceHairEyeReviewRuntimeError, match="component candidate"):
        runtime._eye_receipts(
            eye_geometry_dir=geometry_dir,
            eye_appearance_dir=appearance_dir,
            body_geometry=body_geometry,
        )


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_eye_appearance_rejects_noncanonical_v1(tmp_path: Path, version: object) -> None:
    geometry_dir, appearance_dir, body_geometry = _prepare_eye_receipts(
        tmp_path,
        appearance_version=version,
    )

    with pytest.raises(runtime.SourceHairEyeReviewRuntimeError, match="appearance candidate"):
        runtime._eye_receipts(
            eye_geometry_dir=geometry_dir,
            eye_appearance_dir=appearance_dir,
            body_geometry=body_geometry,
        )


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_eye_receipts_accept_numeric_v1(tmp_path: Path, version: object) -> None:
    geometry_dir, appearance_dir, body_geometry = _prepare_eye_receipts(
        tmp_path,
        component_version=version,
        appearance_version=version,
    )

    component, appearance = runtime._eye_receipts(
        eye_geometry_dir=geometry_dir,
        eye_appearance_dir=appearance_dir,
        body_geometry=body_geometry,
    )

    assert component["version"] == 1
    assert appearance["version"] == 1
