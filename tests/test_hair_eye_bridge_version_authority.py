from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[1]
BRIDGES = ROOT / "bodyrig" / "bridges"
BRIDGE_PATH = BRIDGES / "sith_hair_eye_review_runtime.py"


def _load_bridge():
    previous = list(sys.path)
    try:
        sys.path.insert(0, str(BRIDGES))
        spec = importlib.util.spec_from_file_location("bodyrig_hair_eye_bridge_v1_test", BRIDGE_PATH)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path[:] = previous


bridge = _load_bridge()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _inputs(tmp_path: Path, *, component_version: Any = 1, appearance_version: Any = 1):
    geometry_dir = tmp_path / "eye-geometry"
    appearance_dir = tmp_path / "eye-appearance"
    geometry_dir.mkdir()
    appearance_dir.mkdir()

    left_obj = geometry_dir / "left_eye.obj"
    right_obj = geometry_dir / "right_eye.obj"
    canonical_bake = appearance_dir / "canonical_eye_source_bake.png"
    left_png = appearance_dir / "left_eye_appearance.png"
    right_png = appearance_dir / "right_eye_appearance.png"
    left_obj.write_bytes(b"v 0 0 0\nf 1 1 1\n")
    right_obj.write_bytes(b"v 0 0 0\nf 1 1 1\n")
    canonical_bake.write_bytes(b"\x89PNG\r\n\x1a\ncanonical-eye")
    left_png.write_bytes(b"\x89PNG\r\n\x1a\nleft-eye")
    right_png.write_bytes(b"\x89PNG\r\n\x1a\nright-eye")

    geometry = {
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
        "donorObjSha256": geometry["fittedDonorObjSha256"],
        "leftEyeObjSha256": _sha(left_obj),
        "rightEyeObjSha256": _sha(right_obj),
        "leftEyeFaceCount": 12,
        "rightEyeFaceCount": 13,
        "leftEyeJointIndex": bridge.eye_geometry.LEFT_EYE_JOINT,
        "rightEyeJointIndex": bridge.eye_geometry.RIGHT_EYE_JOINT,
        "explicitEyeGeometry": True,
        "geometryAuthority": "candidate-only",
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
        "method": "canonical-source-eye-bake-v1",
        "targetModelFamily": "female",
        "donorObjSha256": geometry["fittedDonorObjSha256"],
        "sourceReconstructionSha256": geometry["reconstructionSha256"],
        "sourceMeshSha256": geometry["sourceMeshSha256"],
        "sourceTextureSha256": geometry["sourceTextureSha256"],
        "canonicalBakeSha256": _sha(canonical_bake),
        "leftEyeAppearancePngSha256": _sha(left_png),
        "rightEyeAppearancePngSha256": _sha(right_png),
        "leftEyeFaceCount": 12,
        "rightEyeFaceCount": 13,
        "leftMaskPixelCount": 100,
        "rightMaskPixelCount": 101,
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
    _write_json(geometry_dir / "eye-component-candidate.json", component)
    _write_json(appearance_dir / "eye-appearance-candidate.json", appearance)
    return geometry, geometry_dir, appearance_dir


INVALID_V1_VALUES = (True, False, "1", None, [], {}, 2)
VALID_V1_VALUES = (1, 1.0)


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_bridge_rejects_non_numeric_or_boolean_component_v1(tmp_path: Path, version: Any) -> None:
    geometry, geometry_dir, appearance_dir = _inputs(tmp_path, component_version=version)

    with pytest.raises(bridge.HairEyeReviewRuntimeError, match="component candidate format/version mismatch"):
        bridge._validate_eye_inputs(
            geometry=geometry,
            eye_geometry_dir=geometry_dir,
            eye_appearance_dir=appearance_dir,
        )


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_bridge_rejects_non_numeric_or_boolean_appearance_v1(tmp_path: Path, version: Any) -> None:
    geometry, geometry_dir, appearance_dir = _inputs(tmp_path, appearance_version=version)

    with pytest.raises(bridge.HairEyeReviewRuntimeError, match="appearance candidate format/version mismatch"):
        bridge._validate_eye_inputs(
            geometry=geometry,
            eye_geometry_dir=geometry_dir,
            eye_appearance_dir=appearance_dir,
        )


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_bridge_preserves_numeric_component_v1_compatibility(tmp_path: Path, version: Any) -> None:
    geometry, geometry_dir, appearance_dir = _inputs(tmp_path, component_version=version)

    component, appearance, bake = bridge._validate_eye_inputs(
        geometry=geometry,
        eye_geometry_dir=geometry_dir,
        eye_appearance_dir=appearance_dir,
    )

    assert component["version"] == version
    assert appearance["version"] == 1
    assert bake.startswith(b"\x89PNG\r\n\x1a\n")


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_bridge_preserves_numeric_appearance_v1_compatibility(tmp_path: Path, version: Any) -> None:
    geometry, geometry_dir, appearance_dir = _inputs(tmp_path, appearance_version=version)

    component, appearance, bake = bridge._validate_eye_inputs(
        geometry=geometry,
        eye_geometry_dir=geometry_dir,
        eye_appearance_dir=appearance_dir,
    )

    assert component["version"] == 1
    assert appearance["version"] == version
    assert bake.startswith(b"\x89PNG\r\n\x1a\n")
