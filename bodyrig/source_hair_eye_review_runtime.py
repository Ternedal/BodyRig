from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .avatar import AvatarError, validate_vrm1
from .source_hair_body_binding import SourceHairBodyBindingError, build_binding

FORMAT = "bodyrig-source-hair-eye-review-runtime"
VERSION = 1
BRIDGE_FORMAT = "bodyrig-source-hair-eye-review-bridge"
BRIDGE_VERSION = 1
EYE_METADATA_FORMAT = "bodyrig-source-eye-review-runtime-metadata"
EYE_METADATA_VERSION = 1


class SourceHairEyeReviewRuntimeError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _hex(value: Any, *, length: int, label: str) -> str:
    if not isinstance(value, str) or len(value) != length or any(ch not in "0123456789abcdef" for ch in value):
        raise SourceHairEyeReviewRuntimeError(f"{label} is invalid")
    return value


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceHairEyeReviewRuntimeError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SourceHairEyeReviewRuntimeError(f"{label} must be an object")
    return value


def _write_json_create_only(path: Path, value: Mapping[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise SourceHairEyeReviewRuntimeError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SourceHairEyeReviewRuntimeError(f"output already exists: {path}") from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _bridge(path: Path) -> dict[str, Any]:
    value = _read_json(path, label="hair+eye review bridge result")
    required = {
        "format", "version", "baseAvatarVrmSha256", "sourceHairBodyBindingSha256",
        "hairReviewBridgeSha256", "hairMeshIndex", "eyeMeshIndex", "reviewVrmSha256",
        "targetModelFamily", "leftEyeFaceCount", "rightEyeFaceCount",
        "leftEyeRuntimeVertices", "rightEyeRuntimeVertices", "sourceHairRuntimeApplied",
        "sourceEyeSurfaceApplied", "irisIdentityIsolated", "irisAppearanceStatus",
        "cornealMaterialStatus", "eyelashStatus", "physicalSilhouetteReviewRequired",
        "physicalFaceCloseupReviewRequired", "comparisonOnly", "humanReviewRequired",
        "hairComponentAuthority", "eyeComponentAuthority", "productionActivation",
    }
    if set(value) != required or value.get("format") != BRIDGE_FORMAT or value.get("version") != BRIDGE_VERSION:
        raise SourceHairEyeReviewRuntimeError("hair+eye review bridge fields/format do not match v1")
    for field in ("baseAvatarVrmSha256", "sourceHairBodyBindingSha256", "hairReviewBridgeSha256", "reviewVrmSha256"):
        _hex(value.get(field), length=64, label=f"bridge {field}")
    if value.get("targetModelFamily") not in {"female", "male", "neutral"}:
        raise SourceHairEyeReviewRuntimeError("bridge target model family is invalid")
    for field in ("hairMeshIndex", "eyeMeshIndex", "leftEyeFaceCount", "rightEyeFaceCount", "leftEyeRuntimeVertices", "rightEyeRuntimeVertices"):
        item = value.get(field)
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise SourceHairEyeReviewRuntimeError(f"bridge {field} is invalid")
    if (
        value.get("sourceHairRuntimeApplied") is not True
        or value.get("sourceEyeSurfaceApplied") is not True
        or value.get("irisIdentityIsolated") is not False
        or value.get("irisAppearanceStatus") != "review-pending"
        or value.get("cornealMaterialStatus") != "runtime-applied"
        or value.get("eyelashStatus") != "missing"
        or value.get("physicalSilhouetteReviewRequired") is not True
        or value.get("physicalFaceCloseupReviewRequired") is not True
        or value.get("comparisonOnly") is not True
        or value.get("humanReviewRequired") is not True
        or value.get("hairComponentAuthority") is not False
        or value.get("eyeComponentAuthority") is not False
        or value.get("productionActivation") is not False
    ):
        raise SourceHairEyeReviewRuntimeError("hair+eye bridge crossed the review-only authority boundary")
    return value


def _eye_receipts(
    *,
    eye_geometry_dir: Path,
    eye_appearance_dir: Path,
    body_geometry: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    component_path = eye_geometry_dir / "eye-component-candidate.json"
    appearance_path = eye_appearance_dir / "eye-appearance-candidate.json"
    left_obj = eye_geometry_dir / "left_eye.obj"
    right_obj = eye_geometry_dir / "right_eye.obj"
    bake = eye_appearance_dir / "canonical_eye_source_bake.png"
    left_png = eye_appearance_dir / "left_eye_appearance.png"
    right_png = eye_appearance_dir / "right_eye_appearance.png"
    for path in (component_path, appearance_path, left_obj, right_obj, bake, left_png, right_png):
        if not path.is_file():
            raise SourceHairEyeReviewRuntimeError(f"eye runtime authority artifact is missing: {path.name}")
    component = _read_json(component_path, label="eye component candidate")
    appearance = _read_json(appearance_path, label="eye appearance candidate")
    if (
        component.get("format") != "bodyrig-eye-component-candidate"
        or component.get("version") != 1
        or component.get("targetModelFamily") != body_geometry.get("bodyModelGender")
        or component.get("donorObjSha256") != body_geometry.get("fittedDonorObjSha256")
        or component.get("leftEyeObjSha256") != _sha256(left_obj)
        or component.get("rightEyeObjSha256") != _sha256(right_obj)
        or component.get("explicitEyeGeometry") is not True
        or component.get("componentStatus") != "partial"
        or component.get("productionReady") is not False
    ):
        raise SourceHairEyeReviewRuntimeError("eye component candidate no longer binds the body/runtime inputs")
    if (
        appearance.get("format") != "bodyrig-eye-appearance-candidate"
        or appearance.get("version") != 1
        or appearance.get("targetModelFamily") != body_geometry.get("bodyModelGender")
        or appearance.get("donorObjSha256") != body_geometry.get("fittedDonorObjSha256")
        or appearance.get("sourceReconstructionSha256") != body_geometry.get("reconstructionSha256")
        or appearance.get("sourceMeshSha256") != body_geometry.get("sourceMeshSha256")
        or appearance.get("sourceTextureSha256") != body_geometry.get("sourceTextureSha256")
        or appearance.get("canonicalBakeSha256") != _sha256(bake)
        or appearance.get("leftEyeAppearancePngSha256") != _sha256(left_png)
        or appearance.get("rightEyeAppearancePngSha256") != _sha256(right_png)
        or appearance.get("sourceDerivedEyeSurfaceAppearance") is not True
        or appearance.get("irisIdentityIsolated") is not False
        or appearance.get("irisAppearanceStatus") != "review-pending"
        or appearance.get("componentStatus") != "partial"
        or appearance.get("productionReady") is not False
    ):
        raise SourceHairEyeReviewRuntimeError("eye appearance candidate no longer binds the body/runtime inputs")
    if component.get("leftEyeFaceCount") != appearance.get("leftEyeFaceCount") or component.get("rightEyeFaceCount") != appearance.get("rightEyeFaceCount"):
        raise SourceHairEyeReviewRuntimeError("eye geometry and source appearance face authority disagree")
    return component, appearance


def finalize(
    *,
    package_path: str | Path,
    hair_candidate_dir: str | Path,
    eye_geometry_dir: str | Path,
    eye_appearance_dir: str | Path,
    staging_dir: str | Path,
    bodyrig_revision: str,
    bridge_script_sha256: str,
) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    hair_candidate = Path(hair_candidate_dir).expanduser().resolve()
    eye_geometry = Path(eye_geometry_dir).expanduser().resolve()
    eye_appearance = Path(eye_appearance_dir).expanduser().resolve()
    staging = Path(staging_dir).expanduser().resolve()
    revision = _hex(bodyrig_revision, length=40, label="BodyRig revision")
    bridge_script_sha = _hex(bridge_script_sha256, length=64, label="combined bridge script SHA-256")
    binding_path = staging / "source-hair-body-binding.json"
    review_vrm_path = staging / "source-hair-eye-review.vrm"
    bridge_path = staging / "source-hair-eye-review-bridge.json"
    receipt_path = staging / "source-hair-eye-review-runtime.json"
    for path in (binding_path, review_vrm_path, bridge_path):
        if not path.is_file():
            raise SourceHairEyeReviewRuntimeError(f"combined runtime staging artifact is missing: {path.name}")
    if receipt_path.exists():
        raise SourceHairEyeReviewRuntimeError("combined hair+eye runtime receipt is create-only")

    persisted_binding = _read_json(binding_path, label="source hair/body binding")
    try:
        fresh_binding = build_binding(package, hair_candidate)
    except SourceHairBodyBindingError as exc:
        raise SourceHairEyeReviewRuntimeError(f"fresh hair/body binding failed: {exc}") from exc
    if fresh_binding != persisted_binding:
        raise SourceHairEyeReviewRuntimeError("hair/body authority changed during combined runtime build")
    binding_sha = _sha256(binding_path)
    bridge = _bridge(bridge_path)
    review_vrm = review_vrm_path.read_bytes()
    review_sha = _sha256_bytes(review_vrm)
    if bridge["sourceHairBodyBindingSha256"] != binding_sha:
        raise SourceHairEyeReviewRuntimeError("combined bridge binds different hair/body authority bytes")
    if bridge["reviewVrmSha256"] != review_sha:
        raise SourceHairEyeReviewRuntimeError("combined bridge does not bind exact review VRM bytes")
    if bridge["targetModelFamily"] != fresh_binding["sourceGeometryAuthority"]["bodyModelGender"]:
        raise SourceHairEyeReviewRuntimeError("combined bridge model family differs from fresh body authority")

    component, appearance = _eye_receipts(
        eye_geometry_dir=eye_geometry,
        eye_appearance_dir=eye_appearance,
        body_geometry=fresh_binding["sourceGeometryAuthority"],
    )
    if bridge["leftEyeFaceCount"] != component["leftEyeFaceCount"] or bridge["rightEyeFaceCount"] != component["rightEyeFaceCount"]:
        raise SourceHairEyeReviewRuntimeError("combined bridge eye face counts differ from fresh eye authority")

    try:
        document = validate_vrm1(review_vrm)
    except AvatarError as exc:
        raise SourceHairEyeReviewRuntimeError(f"combined hair+eye artifact is not valid VRM 1.0: {exc}") from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    hair_metadata = bodyrig.get("hairReviewRuntime") if isinstance(bodyrig, dict) else None
    eye_metadata = bodyrig.get("eyeReviewRuntime") if isinstance(bodyrig, dict) else None
    if not isinstance(hair_metadata, dict):
        raise SourceHairEyeReviewRuntimeError("combined VRM lost source-hair runtime metadata")
    if not isinstance(eye_metadata, dict):
        raise SourceHairEyeReviewRuntimeError("combined VRM lacks eye runtime metadata")
    expected_eye = {
        "format": EYE_METADATA_FORMAT,
        "version": EYE_METADATA_VERSION,
        "eyeComponentReceiptSha256": _sha256(eye_geometry / "eye-component-candidate.json"),
        "eyeAppearanceReceiptSha256": _sha256(eye_appearance / "eye-appearance-candidate.json"),
        "canonicalEyeBakeSha256": appearance["canonicalBakeSha256"],
        "targetModelFamily": fresh_binding["sourceGeometryAuthority"]["bodyModelGender"],
        "leftEyeJointIndex": int(component["leftEyeJointIndex"]),
        "rightEyeJointIndex": int(component["rightEyeJointIndex"]),
        "sourceEyeSurfaceApplied": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "runtime-applied",
        "eyelashStatus": "missing",
        "skinIndex": 0,
        "physicalFaceCloseupReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "eyeComponentAuthority": False,
        "productionActivation": False,
    }
    if eye_metadata != expected_eye:
        raise SourceHairEyeReviewRuntimeError("combined VRM eye metadata differs from fresh eye/body authority")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "bodyrigRevision": revision,
        "bridgeScriptSha256": bridge_script_sha,
        "bodyId": fresh_binding["bodyId"],
        "packageSha256": fresh_binding["packageSha256"],
        "baseAvatarVrmSha256": bridge["baseAvatarVrmSha256"],
        "sourceHairBodyBindingSha256": binding_sha,
        "hairCandidateReceiptSha256": fresh_binding["hairCandidateReceiptSha256"],
        "eyeComponentReceiptSha256": expected_eye["eyeComponentReceiptSha256"],
        "eyeAppearanceReceiptSha256": expected_eye["eyeAppearanceReceiptSha256"],
        "reviewVrmSha256": review_sha,
        "bridgeResultSha256": _sha256(bridge_path),
        "targetModelFamily": bridge["targetModelFamily"],
        "hairMeshIndex": bridge["hairMeshIndex"],
        "eyeMeshIndex": bridge["eyeMeshIndex"],
        "leftEyeFaceCount": bridge["leftEyeFaceCount"],
        "rightEyeFaceCount": bridge["rightEyeFaceCount"],
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
    _write_json_create_only(receipt_path, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finalize a combined source-hair + explicit-eye review VRM.")
    parser.add_argument("--package", required=True)
    parser.add_argument("--hair-candidate-dir", required=True)
    parser.add_argument("--eye-geometry-dir", required=True)
    parser.add_argument("--eye-appearance-dir", required=True)
    parser.add_argument("--staging-dir", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--bridge-script-sha256", required=True)
    args = parser.parse_args(argv)
    try:
        result = finalize(
            package_path=args.package,
            hair_candidate_dir=args.hair_candidate_dir,
            eye_geometry_dir=args.eye_geometry_dir,
            eye_appearance_dir=args.eye_appearance_dir,
            staging_dir=args.staging_dir,
            bodyrig_revision=args.bodyrig_revision,
            bridge_script_sha256=args.bridge_script_sha256,
        )
        print(json.dumps(result, separators=(",", ":"), allow_nan=False))
        return 0
    except (SourceHairEyeReviewRuntimeError, OSError) as exc:
        print(f"BodyRig hair+eye review runtime: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
