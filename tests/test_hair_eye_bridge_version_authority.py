from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

import sith_hair_eye_review_runtime as bridge  # noqa: E402


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _inputs(
    root: Path,
    *,
    component_version: object = 1,
    appearance_version: object = 1,
) -> tuple[dict[str, object], Path, Path]:
    geometry_dir = root / "eyes"
    appearance_dir = root / "appearance"
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

    geometry: dict[str, object] = {
        "bodyModelGender": "female",
        "fittedDonorObjSha256": "1" * 64,
        "reconstructionSha256": "2" * 64,
        "sourceMeshSha256": "3" * 64,
        "sourceTextureSha256": "4" * 64,
    }
    component = {
        "format": "bodyrig-eye-component-candidate",
        "version": component_version,
        "method": "smplx-eye-joint-lbs-submesh-v1",
        "targetModelFamily": "female",
        "donorObjSha256": "1" * 64,
        "leftEyeObjSha256": _sha(left_obj),
        "rightEyeObjSha256": _sha(right_obj),
        "leftEyeFaceCount": 12,
        "rightEyeFaceCount": 13,
        "leftEyeJointIndex": bridge.eye_geometry.LEFT_EYE_JOINT,
        "rightEyeJointIndex": bridge.eye_geometry.RIGHT_EYE_JOINT,
        "explicitEyeGeometry": True,
        "geometryAuthority": "review-only",
        "sourceDerivedIrisAppearance": False,
        "irisAppearanceStatus": "missing",
        "cornealMaterialStatus": "missing",
        "eyelashStatus": "missing",
        "bodyTopologyModified": False,
        "generativeIdentitySynthesis": False,
        "componentStatus": "partial",
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
    }
    appearance = {
        "format": "bodyrig-eye-appearance-candidate",
        "version": appearance_version,
        "method": "canonical-source-eye-surface-bake-v1",
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
        "leftMaskPixelCount": 100,
        "rightMaskPixelCount": 100,
        "bakeResolution": 1024,
        "sourceDerivedEyeSurfaceAppearance": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "missing",
        "eyelashStatus": "missing",
        "bodyTopologyModified": False,
        "generativeIdentitySynthesis": False,
        "componentStatus": "partial",
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
        "bakeSurfaceDistanceP95": 0.001,
        "bakeSurfaceDistanceMax": 0.002,
    }
    (geometry_dir / "eye-component-candidate.json").write_text(
        json.dumps(component), encoding="utf-8"
    )
    (appearance_dir / "eye-appearance-candidate.json").write_text(
        json.dumps(appearance), encoding="utf-8"
    )
    return geometry, geometry_dir, appearance_dir


@pytest.mark.parametrize("version", (True, False, "1", None, 2))
def test_bridge_rejects_non_numeric_or_boolean_eye_component_v1(
    tmp_path: Path, version: object
) -> None:
    geometry, geometry_dir, appearance_dir = _inputs(
        tmp_path, component_version=version
    )
    with pytest.raises(bridge.HairEyeReviewRuntimeError, match="component candidate format/version"):
        bridge._validate_eye_inputs(
            geometry=geometry,
            eye_geometry_dir=geometry_dir,
            eye_appearance_dir=appearance_dir,
        )


@pytest.mark.parametrize("version", (True, False, "1", None, 2))
def test_bridge_rejects_non_numeric_or_boolean_eye_appearance_v1(
    tmp_path: Path, version: object
) -> None:
    geometry, geometry_dir, appearance_dir = _inputs(
        tmp_path, appearance_version=version
    )
    with pytest.raises(bridge.HairEyeReviewRuntimeError, match="appearance candidate format/version"):
        bridge._validate_eye_inputs(
            geometry=geometry,
            eye_geometry_dir=geometry_dir,
            eye_appearance_dir=appearance_dir,
        )


@pytest.mark.parametrize("version", (1, 1.0))
def test_bridge_accepts_numeric_v1_for_both_eye_receipts(
    tmp_path: Path, version: object
) -> None:
    geometry, geometry_dir, appearance_dir = _inputs(
        tmp_path,
        component_version=version,
        appearance_version=version,
    )
    component, appearance, bake = bridge._validate_eye_inputs(
        geometry=geometry,
        eye_geometry_dir=geometry_dir,
        eye_appearance_dir=appearance_dir,
    )
    assert component["version"] == version
    assert appearance["version"] == version
    assert bake.startswith(b"\x89PNG\r\n\x1a\n")
