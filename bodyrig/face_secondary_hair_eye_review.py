from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Mapping

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .fine_identity_application import (
    FineIdentityApplicationError,
    validate_requirement as validate_fine_identity_requirement,
)
from .high_fidelity_face_secondary_runtime import (
    JOINT_NAMES,
    REVIEW_METADATA_FORMAT,
    _append_geometry,
    _bodyrig,
    _joint_world,
    _lash,
    _oval_prism,
    _tooth_row,
)
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-face-secondary-on-hair-eye-review-runtime"
VERSION = 1
POLICY_REVISION = "bodyrig-face-secondary-on-hair-eye-review-v1"
SOURCE_FORMAT = "bodyrig-source-hair-eye-review-runtime"
SOURCE_VERSION = 1
VRM_NAME = "face-secondary-hair-eye-review.vrm"
RECEIPT_NAME = "face-secondary-hair-eye-review-runtime.json"
EMBEDDED_KEY = "faceSecondaryHairEyeReviewRuntime"
SOURCE_RECEIPT_NAME = "source-hair-eye-review-runtime.json"
SOURCE_VRM_NAME = "source-hair-eye-review.vrm"
SHA_FIELDS = {
    "bridgeScriptSha256",
    "packageSha256",
    "baseAvatarVrmSha256",
    "sourceHairBodyBindingSha256",
    "hairCandidateReceiptSha256",
    "eyeComponentReceiptSha256",
    "eyeAppearanceReceiptSha256",
    "reviewVrmSha256",
    "bridgeResultSha256",
}
SOURCE_FIELDS = {
    "format", "version", "bodyrigRevision", "bridgeScriptSha256", "bodyId", "packageSha256",
    "baseAvatarVrmSha256", "sourceHairBodyBindingSha256", "hairCandidateReceiptSha256",
    "eyeComponentReceiptSha256", "eyeAppearanceReceiptSha256", "reviewVrmSha256",
    "bridgeResultSha256", "targetModelFamily", "hairMeshIndex", "eyeMeshIndex",
    "leftEyeFaceCount", "rightEyeFaceCount", "sourceHairRuntimeApplied", "sourceEyeSurfaceApplied",
    "irisIdentityIsolated", "irisAppearanceStatus", "cornealMaterialStatus", "eyelashStatus",
    "runtimeIntegrationStatus", "physicalSilhouetteReviewRequired", "physicalFaceCloseupReviewRequired",
    "comparisonOnly", "humanReviewRequired", "hairComponentAuthority", "eyeComponentAuthority",
    "productionActivation",
}


class FaceSecondaryHairEyeReviewError(RuntimeError):
    pass


def _is_v1(value: Any) -> bool:
    return not isinstance(value, bool) and value == VERSION


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise FaceSecondaryHairEyeReviewError(f"{label} is not a canonical SHA-256")
    return clean


def _revision(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if len(clean) != 40 or any(ch not in "0123456789abcdef" for ch in clean):
        raise FaceSecondaryHairEyeReviewError("BodyRig revision is not canonical")
    return clean


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FaceSecondaryHairEyeReviewError(f"{label} is missing or symlinked")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaceSecondaryHairEyeReviewError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise FaceSecondaryHairEyeReviewError(f"{label} must be an object")
    return value


def _validate_source_receipt(value: Mapping[str, Any], *, receipt_path: Path, vrm_path: Path, package_sha: str, body_id: str, revision: str) -> dict[str, Any]:
    if set(value) != SOURCE_FIELDS or value.get("format") != SOURCE_FORMAT or not _is_v1(value.get("version")):
        raise FaceSecondaryHairEyeReviewError("hair+eye runtime receipt fields/format do not match v1")
    if value.get("bodyrigRevision") != revision:
        raise FaceSecondaryHairEyeReviewError("hair+eye runtime belongs to a different BodyRig revision")
    if value.get("bodyId") != body_id or value.get("packageSha256") != package_sha:
        raise FaceSecondaryHairEyeReviewError("hair+eye runtime targets different body/package bytes")
    for field in SHA_FIELDS:
        _sha(value.get(field), label=f"hair+eye {field}")
    if value.get("reviewVrmSha256") != _sha256_file(vrm_path):
        raise FaceSecondaryHairEyeReviewError("hair+eye review VRM bytes changed after receipt publication")
    for field in ("hairMeshIndex", "eyeMeshIndex", "leftEyeFaceCount", "rightEyeFaceCount"):
        item = value.get(field)
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise FaceSecondaryHairEyeReviewError(f"hair+eye {field} is invalid")
    if value.get("targetModelFamily") not in {"female", "male", "neutral"}:
        raise FaceSecondaryHairEyeReviewError("hair+eye target model family is invalid")
    if (
        value.get("sourceHairRuntimeApplied") is not True
        or value.get("sourceEyeSurfaceApplied") is not True
        or value.get("irisIdentityIsolated") is not False
        or value.get("irisAppearanceStatus") != "review-pending"
        or value.get("cornealMaterialStatus") != "runtime-applied"
        or value.get("eyelashStatus") != "missing"
        or value.get("runtimeIntegrationStatus") != "hair-and-eyes-review-artifact-ready"
        or value.get("physicalSilhouetteReviewRequired") is not True
        or value.get("physicalFaceCloseupReviewRequired") is not True
        or value.get("comparisonOnly") is not True
        or value.get("humanReviewRequired") is not True
        or value.get("hairComponentAuthority") is not False
        or value.get("eyeComponentAuthority") is not False
        or value.get("productionActivation") is not False
    ):
        raise FaceSecondaryHairEyeReviewError("hair+eye runtime crossed its review-only authority boundary")
    return dict(value)


def _package_authority(package: Path) -> tuple[str, str]:
    try:
        validated = validate_package(package)
    except MRBodyError as exc:
        raise FaceSecondaryHairEyeReviewError(f"source package is invalid: {exc}") from exc
    return str(validated.manifest["id"]), _sha256_file(package)


def _primitives(document: Mapping[str, Any]) -> tuple[list[tuple[str, list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[int, int, int]], int]], dict[str, tuple[int, tuple[float, float, float]]], float]:
    joint_values = {name: _joint_world(document, name) for name in JOINT_NAMES}
    head_joint, _head = joint_values["smplx_head"]
    jaw_joint, jaw = joint_values["smplx_jaw"]
    _left_joint, left_eye = joint_values["smplx_left_eye"]
    _right_joint, right_eye = joint_values["smplx_right_eye"]
    dx = left_eye[0] - right_eye[0]
    dy = left_eye[1] - right_eye[1]
    dz = left_eye[2] - right_eye[2]
    interocular = (dx * dx + dy * dy + dz * dz) ** 0.5
    if not 0.015 <= interocular <= 0.20:
        raise FaceSecondaryHairEyeReviewError("SMPL-X interocular scale is outside the accepted human range")
    eye_mid = tuple((left_eye[index] + right_eye[index]) * 0.5 for index in range(3))
    mouth = tuple(jaw[index] + (eye_mid[index] - jaw[index]) * 0.36 for index in range(3))
    mouth = (mouth[0], mouth[1], mouth[2] - interocular * 0.055)
    result: list[tuple[str, list[tuple[float, float, float]], list[tuple[float, float, float]], list[tuple[int, int, int]], int]] = []
    for role, geometry in (
        ("mouth_interior", _oval_prism(mouth, (interocular * 0.90, interocular * 0.22, interocular * 0.085), jaw_joint)),
        ("upper_teeth", _tooth_row((mouth[0], mouth[1] + interocular * 0.046, mouth[2] + interocular * 0.030), (interocular * 0.70, interocular * 0.078, interocular * 0.050), head_joint, upper=True)),
        ("lower_teeth", _tooth_row((mouth[0], mouth[1] - interocular * 0.046, mouth[2] + interocular * 0.026), (interocular * 0.66, interocular * 0.068, interocular * 0.046), jaw_joint, upper=False)),
        ("left_eyelashes", _lash(left_eye, interocular, head_joint)),
        ("right_eyelashes", _lash(right_eye, interocular, head_joint)),
    ):
        positions, normals, faces, joint = geometry
        result.append((role, positions, normals, faces, joint))
    return result, joint_values, interocular


def build(package_path: str | Path, hair_eye_runtime_dir: str | Path, output_dir: str | Path, *, bodyrig_revision: str) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    source_root = Path(hair_eye_runtime_dir).expanduser().resolve()
    root = Path(output_dir).expanduser().resolve()
    revision = _revision(bodyrig_revision)
    if root.exists():
        raise FaceSecondaryHairEyeReviewError("face-secondary hair+eye review output is create-only")
    if not package.is_file() or package.is_symlink():
        raise FaceSecondaryHairEyeReviewError("source package is missing or symlinked")
    body_id, package_sha = _package_authority(package)
    source_receipt_path = source_root / SOURCE_RECEIPT_NAME
    source_vrm_path = source_root / SOURCE_VRM_NAME
    source_receipt = _validate_source_receipt(
        _read_object(source_receipt_path, label="hair+eye runtime receipt"),
        receipt_path=source_receipt_path,
        vrm_path=source_vrm_path,
        package_sha=package_sha,
        body_id=body_id,
        revision=revision,
    )
    source_vrm = source_vrm_path.read_bytes()
    try:
        document, binary = _read_glb(source_vrm)
    except PbrMaterialError as exc:
        raise FaceSecondaryHairEyeReviewError(str(exc)) from exc
    bodyrig = _bodyrig(document)
    fine_requirement_raw = bodyrig.get("fineIdentityRequirement")
    if fine_requirement_raw is not None:
        try:
            validate_fine_identity_requirement(fine_requirement_raw)
        except FineIdentityApplicationError as exc:
            raise FaceSecondaryHairEyeReviewError(
                f"photoidentical fine-identity requirement is invalid: {exc}"
            ) from exc
        raise FaceSecondaryHairEyeReviewError(
            "photoidentical fine-identity requires source-derived dental/oral geometry; "
            "refusing deterministic generic mouth/teeth face-secondary runtime"
        )
    appearance_transfer = bodyrig.get("appearanceTransfer")
    if not isinstance(appearance_transfer, dict):
        raise FaceSecondaryHairEyeReviewError(
            "hair+eye review VRM lacks promoted appearanceTransfer authority required by HFN continuation"
        )
    _sha(appearance_transfer.get("activeBaseColorSha256"), label="appearanceTransfer active base-color SHA-256")
    appearance_transfer_before = json.loads(
        json.dumps(appearance_transfer, ensure_ascii=False, sort_keys=True, allow_nan=False)
    )
    if EMBEDDED_KEY in bodyrig or "faceSecondaryReviewRuntime" in bodyrig:
        raise FaceSecondaryHairEyeReviewError("hair+eye review VRM already contains face-secondary review metadata")
    hair_metadata = bodyrig.get("hairReviewRuntime")
    eye_metadata = bodyrig.get("eyeReviewRuntime")
    if not isinstance(hair_metadata, dict) or not isinstance(eye_metadata, dict):
        raise FaceSecondaryHairEyeReviewError("hair+eye review VRM lacks embedded hair/eye runtime metadata")
    if (
        eye_metadata.get("format") != "bodyrig-source-eye-review-runtime-metadata"
        or not _is_v1(eye_metadata.get("version"))
        or eye_metadata.get("sourceEyeSurfaceApplied") is not True
        or eye_metadata.get("irisIdentityIsolated") is not False
        or eye_metadata.get("irisAppearanceStatus") != "review-pending"
        or eye_metadata.get("cornealMaterialStatus") != "runtime-applied"
        or eye_metadata.get("eyelashStatus") != "missing"
        or eye_metadata.get("comparisonOnly") is not True
        or eye_metadata.get("humanReviewRequired") is not True
        or eye_metadata.get("eyeComponentAuthority") is not False
        or eye_metadata.get("productionActivation") is not False
    ):
        raise FaceSecondaryHairEyeReviewError("embedded eye review metadata is not canonical review-only authority")

    primitives, joint_values, interocular = _primitives(document)
    try:
        review_vrm = _append_geometry(document, binary, primitives)
        review_document, review_binary = _read_glb(review_vrm)
    except (PbrMaterialError, RuntimeError, ValueError) as exc:
        raise FaceSecondaryHairEyeReviewError(str(exc)) from exc
    review_bodyrig = _bodyrig(review_document)
    if review_bodyrig.get("appearanceTransfer") != appearance_transfer_before:
        raise FaceSecondaryHairEyeReviewError(
            "face-secondary composition changed promoted appearanceTransfer authority required by HFN continuation"
        )
    metadata = {
        "format": REVIEW_METADATA_FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "sourcePackageSha256": package_sha,
        "sourceHairEyeRuntimeReceiptSha256": _sha256_file(source_receipt_path),
        "sourceHairEyeReviewVrmSha256": _sha256_bytes(source_vrm),
        "canonicalBodyId": body_id,
        "bodyrigRevision": revision,
        "smplxAnchorJoints": {name: value[0] for name, value in joint_values.items()},
        "interocularDistanceMeters": round(interocular, 8),
        "eyebrowAppearanceSource": "existing-source-derived-face-basecolor",
        "lipBoundarySource": "existing-source-derived-face-basecolor",
        "mouthInteriorGeometry": "deterministic-rounded-oval-cavity-v2",
        "teethGeometry": "deterministic-individual-rounded-dental-row-v2",
        "eyelashGeometry": "deterministic-smplx-head-anchored-tapered-ribbon-v2",
        "semanticAnchorAuthority": "licensed-smplx-joint-topology-v1",
        "sourceHairPreserved": True,
        "sourceEyeSurfacePreserved": True,
        "irisIdentityIsolated": False,
        "sourceDerivedIdentitySynthesis": False,
        "generativeIdentitySynthesis": False,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "faceSecondaryComponentAuthority": False,
        "packageMutationPerformed": False,
        "productionActivation": False,
    }
    review_bodyrig[EMBEDDED_KEY] = metadata
    review_vrm = _write_glb(review_document, review_binary)
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "bodyrigRevision": revision,
        "canonicalBodyId": body_id,
        "sourcePackageSha256": package_sha,
        "sourceHairEyeRuntimeReceiptSha256": metadata["sourceHairEyeRuntimeReceiptSha256"],
        "sourceHairEyeReviewVrmSha256": metadata["sourceHairEyeReviewVrmSha256"],
        "reviewVrmSha256": _sha256_bytes(review_vrm),
        "candidateComponents": {
            "eyebrow_appearance": "partial",
            "lip_boundary": "partial",
            "mouth_interior": "partial",
            "teeth": "partial",
            "eyelashes": "partial",
        },
        "sourceHairPreserved": True,
        "sourceEyeSurfacePreserved": True,
        "irisIdentityIsolated": False,
        "genericSecondaryAnatomy": True,
        "sourceDerivedIdentitySynthesis": False,
        "generativeIdentitySynthesis": False,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "faceSecondaryComponentAuthority": False,
        "packageMutationPerformed": False,
        "productionActivation": False,
    }
    root.mkdir(parents=True)
    try:
        (root / VRM_NAME).write_bytes(review_vrm)
        raw = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
        fd = os.open(root / RECEIPT_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        for path in (root / VRM_NAME, root / RECEIPT_NAME):
            path.unlink(missing_ok=True)
        try:
            root.rmdir()
        except OSError:
            pass
        raise
    return {**receipt, "reviewVrmPath": str(root / VRM_NAME), "receiptPath": str(root / RECEIPT_NAME)}


def read_runtime(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    vrm_path = root / VRM_NAME
    receipt_path = root / RECEIPT_NAME
    value = _read_object(receipt_path, label="face-secondary hair+eye runtime receipt")
    if value.get("format") != FORMAT or not _is_v1(value.get("version")) or value.get("policyRevision") != POLICY_REVISION:
        raise FaceSecondaryHairEyeReviewError("face-secondary hair+eye runtime receipt format/version mismatch")
    if value.get("reviewVrmSha256") != _sha256_file(vrm_path):
        raise FaceSecondaryHairEyeReviewError("face-secondary hair+eye review VRM bytes changed")
    if (
        value.get("sourceHairPreserved") is not True
        or value.get("sourceEyeSurfacePreserved") is not True
        or value.get("irisIdentityIsolated") is not False
        or value.get("genericSecondaryAnatomy") is not True
        or value.get("sourceDerivedIdentitySynthesis") is not False
        or value.get("generativeIdentitySynthesis") is not False
        or value.get("comparisonOnly") is not True
        or value.get("humanReviewRequired") is not True
        or value.get("faceSecondaryComponentAuthority") is not False
        or value.get("packageMutationPerformed") is not False
        or value.get("productionActivation") is not False
    ):
        raise FaceSecondaryHairEyeReviewError("face-secondary hair+eye runtime crossed review-only authority")
    try:
        document, _binary = _read_glb(vrm_path.read_bytes())
    except PbrMaterialError as exc:
        raise FaceSecondaryHairEyeReviewError(str(exc)) from exc
    embedded = _bodyrig(document).get(EMBEDDED_KEY)
    if (
        not isinstance(embedded, dict)
        or embedded.get("format") != REVIEW_METADATA_FORMAT
        or not _is_v1(embedded.get("version"))
        or embedded.get("policyRevision") != POLICY_REVISION
        or embedded.get("sourceHairEyeRuntimeReceiptSha256") != value.get("sourceHairEyeRuntimeReceiptSha256")
        or embedded.get("sourceHairEyeReviewVrmSha256") != value.get("sourceHairEyeReviewVrmSha256")
        or embedded.get("canonicalBodyId") != value.get("canonicalBodyId")
        or embedded.get("bodyrigRevision") != value.get("bodyrigRevision")
    ):
        raise FaceSecondaryHairEyeReviewError("embedded face-secondary hair+eye runtime authority is stale")
    return {**value, "reviewVrmPath": str(vrm_path), "receiptPath": str(receipt_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compose deterministic review-only face-secondary anatomy onto a hash-bound source hair+eye review VRM.")
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--package", required=True)
    build_parser.add_argument("--hair-eye-runtime", required=True)
    build_parser.add_argument("--output-dir", required=True)
    build_parser.add_argument("--bodyrig-revision", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.package, args.hair_eye_runtime, args.output_dir, bodyrig_revision=args.bodyrig_revision)
        else:
            result = read_runtime(args.output_dir)
        print(json.dumps(result, separators=(",", ":"), allow_nan=False))
        return 0
    except (FaceSecondaryHairEyeReviewError, OSError, MRBodyError, PbrMaterialError) as exc:
        print(f"BodyRig face-secondary hair+eye review runtime: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
