from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import bodyrig.source_hair_eye_review_runtime as runtime


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "build-source-hair-eye-review-runtime.ps1"
BRIDGE = ROOT / "bodyrig" / "bridges" / "sith_hair_eye_review_runtime.py"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _bridge_value() -> dict[str, object]:
    return {
        "format": "bodyrig-source-hair-eye-review-bridge",
        "version": 1,
        "baseAvatarVrmSha256": "a" * 64,
        "sourceHairBodyBindingSha256": "b" * 64,
        "hairReviewBridgeSha256": "c" * 64,
        "hairMeshIndex": 1,
        "eyeMeshIndex": 2,
        "reviewVrmSha256": "d" * 64,
        "targetModelFamily": "female",
        "leftEyeFaceCount": 12,
        "rightEyeFaceCount": 12,
        "leftEyeRuntimeVertices": 20,
        "rightEyeRuntimeVertices": 20,
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


def test_bridge_result_requires_visible_hair_eye_runtime_without_granting_authority(tmp_path: Path) -> None:
    path = tmp_path / "bridge.json"
    value = _bridge_value()
    path.write_text(json.dumps(value), encoding="utf-8")

    parsed = runtime._bridge(path)

    assert parsed["sourceHairRuntimeApplied"] is True
    assert parsed["sourceEyeSurfaceApplied"] is True
    assert parsed["cornealMaterialStatus"] == "runtime-applied"
    assert parsed["hairComponentAuthority"] is False
    assert parsed["eyeComponentAuthority"] is False
    assert parsed["productionActivation"] is False


def test_bridge_result_rejects_fake_eye_or_production_pass(tmp_path: Path) -> None:
    path = tmp_path / "bridge.json"
    value = _bridge_value()
    value["eyeComponentAuthority"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(runtime.SourceHairEyeReviewRuntimeError, match="review-only"):
        runtime._bridge(path)

    value = _bridge_value()
    value["productionActivation"] = True
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(runtime.SourceHairEyeReviewRuntimeError, match="review-only"):
        runtime._bridge(path)


def test_eye_runtime_revalidates_geometry_and_source_bake_bytes(tmp_path: Path) -> None:
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
        "version": 1,
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
        "version": 1,
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
    (geometry_dir / "eye-component-candidate.json").write_text(json.dumps(component), encoding="utf-8")
    (appearance_dir / "eye-appearance-candidate.json").write_text(json.dumps(appearance), encoding="utf-8")

    parsed_component, parsed_appearance = runtime._eye_receipts(
        eye_geometry_dir=geometry_dir,
        eye_appearance_dir=appearance_dir,
        body_geometry=body_geometry,
    )
    assert parsed_component["leftEyeFaceCount"] == 12
    assert parsed_appearance["canonicalBakeSha256"] == _sha(bake)

    (appearance_dir / "canonical_eye_source_bake.png").write_bytes(bake + b"tampered")
    with pytest.raises(runtime.SourceHairEyeReviewRuntimeError, match="no longer binds"):
        runtime._eye_receipts(
            eye_geometry_dir=geometry_dir,
            eye_appearance_dir=appearance_dir,
            body_geometry=body_geometry,
        )


def test_operator_builds_one_visible_hair_eye_review_vrm() -> None:
    wrapper = WRAPPER.read_text(encoding="utf-8")
    bridge = BRIDGE.read_text(encoding="utf-8")

    for marker in (
        '"--hair-candidate-dir", $hairWsl',
        '"--eye-geometry-dir", $eyeGeometryWsl',
        '"--eye-appearance-dir", $eyeAppearanceWsl',
        '"--smplx-uv-obj", $uvObj',
        'source-hair-eye-review.vrm',
        'Hair:            RUNTIME APPLIED',
        'Eye surface:     SOURCE-BAKED RUNTIME APPLIED',
        'Cornea:          RUNTIME APPLIED',
    ):
        assert marker in wrapper

    for marker in (
        'sourceEyeSurfaceApplied',
        'cornealMaterialStatus',
        '"runtime-applied"',
        'BodyRigSourceEyeReviewMesh',
        'BodyRigSourceEyeSurface',
        'BodyRigCorneaReview',
        '"skin": 0',
        'SURFACE_SCALE = 1.0015',
        'CORNEA_SCALE = 1.012',
        '"hairComponentAuthority": False',
        '"eyeComponentAuthority": False',
        '"productionActivation": False',
    ):
        assert marker in bridge
