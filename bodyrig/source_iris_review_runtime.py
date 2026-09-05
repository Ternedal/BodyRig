from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from typing import Any, Mapping

from .avatar import AvatarError, validate_vrm1
from .source_iris_isolation import SourceIrisIsolationError, read_candidate
from .source_iris_isolation_review import SourceIrisIsolationReviewError, read_review

FORMAT = "bodyrig-source-iris-reviewed-runtime"
VERSION = 1
BASE_RUNTIME_FORMAT = "bodyrig-source-hair-eye-review-runtime"
BASE_RUNTIME_VERSION = 1
EYE_METADATA_FORMAT = "bodyrig-source-eye-review-runtime-metadata"
EYE_METADATA_VERSION = 1
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
BASE_VRM_NAME = "source-hair-eye-review.vrm"
BASE_RECEIPT_NAME = "source-hair-eye-review-runtime.json"
OUTPUT_VRM_NAME = "source-hair-eye-iris-reviewed.vrm"
OUTPUT_RECEIPT_NAME = "source-hair-eye-iris-reviewed-runtime.json"


class SourceIrisReviewRuntimeError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceIrisReviewRuntimeError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise SourceIrisReviewRuntimeError(f"{label} must be a JSON object")
    return value


def _write_json_create_only(path: Path, value: Mapping[str, Any]) -> None:
    raw = (json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SourceIrisReviewRuntimeError(f"refusing to overwrite reviewed iris runtime receipt: {path}") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or not SHA_RE.fullmatch(value):
        raise SourceIrisReviewRuntimeError(f"{label} is not canonical lowercase SHA-256")
    return value


def _revision(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not REVISION_RE.fullmatch(clean):
        raise SourceIrisReviewRuntimeError(f"{label} is not a canonical lowercase Git SHA")
    return clean


def _base_runtime(runtime_dir: Path) -> tuple[dict[str, Any], Path, Path, dict[str, Any]]:
    vrm_path = runtime_dir / BASE_VRM_NAME
    receipt_path = runtime_dir / BASE_RECEIPT_NAME
    if not vrm_path.is_file() or not receipt_path.is_file():
        raise SourceIrisReviewRuntimeError("combined source hair+eye runtime is missing its canonical VRM/receipt")
    receipt = _read_json(receipt_path, label="combined source hair+eye runtime receipt")
    required = {
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
    if set(receipt) != required or receipt.get("format") != BASE_RUNTIME_FORMAT or receipt.get("version") != BASE_RUNTIME_VERSION:
        raise SourceIrisReviewRuntimeError("combined source hair+eye runtime receipt fields/format do not match v1")
    _revision(receipt.get("bodyrigRevision"), label="base runtime BodyRig revision")
    for field in (
        "bridgeScriptSha256", "packageSha256", "baseAvatarVrmSha256", "sourceHairBodyBindingSha256",
        "hairCandidateReceiptSha256", "eyeComponentReceiptSha256", "eyeAppearanceReceiptSha256",
        "reviewVrmSha256", "bridgeResultSha256",
    ):
        _sha(receipt.get(field), label=f"base runtime {field}")
    if receipt.get("targetModelFamily") not in {"female", "male", "neutral"}:
        raise SourceIrisReviewRuntimeError("combined runtime target model family is invalid")
    if (
        receipt.get("sourceHairRuntimeApplied") is not True
        or receipt.get("sourceEyeSurfaceApplied") is not True
        or receipt.get("irisIdentityIsolated") is not False
        or receipt.get("irisAppearanceStatus") != "review-pending"
        or receipt.get("cornealMaterialStatus") != "runtime-applied"
        or receipt.get("eyelashStatus") != "missing"
        or receipt.get("runtimeIntegrationStatus") != "hair-and-eyes-review-artifact-ready"
        or receipt.get("physicalSilhouetteReviewRequired") is not True
        or receipt.get("physicalFaceCloseupReviewRequired") is not True
        or receipt.get("comparisonOnly") is not True
        or receipt.get("humanReviewRequired") is not True
        or receipt.get("hairComponentAuthority") is not False
        or receipt.get("eyeComponentAuthority") is not False
        or receipt.get("productionActivation") is not False
    ):
        raise SourceIrisReviewRuntimeError("combined source hair+eye runtime crossed its review-only authority boundary")
    if receipt["reviewVrmSha256"] != _sha256(vrm_path):
        raise SourceIrisReviewRuntimeError("combined runtime receipt no longer binds exact review VRM bytes")
    try:
        document = validate_vrm1(vrm_path.read_bytes())
    except AvatarError as exc:
        raise SourceIrisReviewRuntimeError(f"combined runtime is not valid VRM 1.0: {exc}") from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    eye = bodyrig.get("eyeReviewRuntime") if isinstance(bodyrig, dict) else None
    if not isinstance(eye, dict):
        raise SourceIrisReviewRuntimeError("combined runtime lost embedded eye review metadata")
    required_eye = {
        "format", "version", "eyeComponentReceiptSha256", "eyeAppearanceReceiptSha256",
        "canonicalEyeBakeSha256", "targetModelFamily", "leftEyeJointIndex", "rightEyeJointIndex",
        "sourceEyeSurfaceApplied", "irisIdentityIsolated", "irisAppearanceStatus", "cornealMaterialStatus",
        "eyelashStatus", "skinIndex", "physicalFaceCloseupReviewRequired", "comparisonOnly",
        "humanReviewRequired", "eyeComponentAuthority", "productionActivation",
    }
    if set(eye) != required_eye or eye.get("format") != EYE_METADATA_FORMAT or eye.get("version") != EYE_METADATA_VERSION:
        raise SourceIrisReviewRuntimeError("embedded eye review metadata fields/format do not match v1")
    if eye.get("eyeAppearanceReceiptSha256") != receipt["eyeAppearanceReceiptSha256"]:
        raise SourceIrisReviewRuntimeError("embedded eye runtime binds different eye appearance authority")
    if eye.get("targetModelFamily") != receipt["targetModelFamily"]:
        raise SourceIrisReviewRuntimeError("embedded eye runtime target family differs from runtime receipt")
    _sha(eye.get("canonicalEyeBakeSha256"), label="embedded canonical eye bake SHA")
    if (
        eye.get("sourceEyeSurfaceApplied") is not True
        or eye.get("irisIdentityIsolated") is not False
        or eye.get("irisAppearanceStatus") != "review-pending"
        or eye.get("cornealMaterialStatus") != "runtime-applied"
        or eye.get("eyelashStatus") != "missing"
        or eye.get("physicalFaceCloseupReviewRequired") is not True
        or eye.get("comparisonOnly") is not True
        or eye.get("humanReviewRequired") is not True
        or eye.get("eyeComponentAuthority") is not False
        or eye.get("productionActivation") is not False
    ):
        raise SourceIrisReviewRuntimeError("embedded eye review metadata crossed the review-pending boundary")
    return receipt, vrm_path, receipt_path, eye


def build_reviewed_runtime(
    *,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    bodyrig_revision: str,
    output_dir: str | Path,
) -> dict[str, Any]:
    revision = _revision(bodyrig_revision, label="reviewed runtime BodyRig revision")
    base_dir = Path(base_runtime_dir).expanduser().resolve()
    candidate_dir = Path(iris_candidate_dir).expanduser().resolve()
    source_dir = Path(source_eye_appearance_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise SourceIrisReviewRuntimeError(f"reviewed iris runtime output already exists: {output}")
    if not base_dir.is_dir() or not candidate_dir.is_dir() or not source_dir.is_dir():
        raise SourceIrisReviewRuntimeError("reviewed iris runtime authority directories are missing")

    base_receipt, base_vrm, base_receipt_path, eye_metadata = _base_runtime(base_dir)
    try:
        candidate = read_candidate(candidate_dir, source_eye_appearance_dir=source_dir)
        review = read_review(candidate_dir=candidate_dir, source_eye_appearance_dir=source_dir)
    except (SourceIrisIsolationError, SourceIrisIsolationReviewError) as exc:
        raise SourceIrisReviewRuntimeError(f"iris isolation authority failed: {exc}") from exc
    if candidate.get("bodyrigRevision") != revision or review.get("bodyrigRevision") != revision:
        raise SourceIrisReviewRuntimeError("iris candidate/review revision differs from reviewed runtime checkout")
    if review.get("irisIdentityIsolated") is not True or review.get("irisAppearanceStatus") != "source-isolated-review-pass":
        raise SourceIrisReviewRuntimeError("iris isolation human review has not passed")
    if review.get("eyeComponentAuthority") is not False or review.get("eyesPromotionEligible") is not False or review.get("productionActivation") is not False:
        raise SourceIrisReviewRuntimeError("iris isolation review crossed eye-component/promotion/production authority")
    if candidate.get("sourceEyeAppearanceReceiptSha256") != base_receipt["eyeAppearanceReceiptSha256"]:
        raise SourceIrisReviewRuntimeError("iris isolation was reviewed against different eye appearance authority")
    if candidate.get("sourceCanonicalEyeBakeSha256") != eye_metadata["canonicalEyeBakeSha256"]:
        raise SourceIrisReviewRuntimeError("iris isolation source bake differs from the exact eye texture rendered in the base VRM")
    if candidate.get("targetModelFamily") != base_receipt["targetModelFamily"]:
        raise SourceIrisReviewRuntimeError("iris isolation target family differs from base eye runtime")

    candidate_path = Path(str(candidate["candidatePath"])).resolve()
    review_path = Path(str(review["reviewPath"])).resolve()
    output.mkdir(parents=True, exist_ok=False)
    output_vrm = output / OUTPUT_VRM_NAME
    output_receipt = output / OUTPUT_RECEIPT_NAME
    created: list[Path] = []
    try:
        shutil.copyfile(base_vrm, output_vrm)
        created.append(output_vrm)
        base_vrm_sha = _sha256(base_vrm)
        reviewed_vrm_sha = _sha256(output_vrm)
        if reviewed_vrm_sha != base_vrm_sha or output_vrm.read_bytes() != base_vrm.read_bytes():
            raise SourceIrisReviewRuntimeError("reviewed iris runtime must preserve the base VRM byte-for-byte")
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "bodyrigRevision": revision,
            "baseRuntimeBodyrigRevision": base_receipt["bodyrigRevision"],
            "baseRuntimeReceiptSha256": _sha256(base_receipt_path),
            "baseReviewVrmSha256": base_vrm_sha,
            "reviewedVrmSha256": reviewed_vrm_sha,
            "irisCandidateSha256": _sha256(candidate_path),
            "irisReviewSha256": _sha256(review_path),
            "sourceEyeAppearanceReceiptSha256": candidate["sourceEyeAppearanceReceiptSha256"],
            "canonicalEyeBakeSha256": candidate["sourceCanonicalEyeBakeSha256"],
            "sourceLeftEyeAppearanceSha256": candidate["sourceLeftEyeAppearanceSha256"],
            "sourceRightEyeAppearanceSha256": candidate["sourceRightEyeAppearanceSha256"],
            "targetModelFamily": candidate["targetModelFamily"],
            "runtimeBytesUnchanged": True,
            "sourceEyePixelsUnchanged": True,
            "embeddedEyeRuntimeStillReviewPending": True,
            "irisReviewOverlayApplied": True,
            "irisIdentityIsolated": True,
            "irisAppearanceStatus": "source-isolated-review-pass",
            "cornealMaterialStatus": "runtime-applied",
            "eyelashStatus": "missing",
            "eyeComponentAuthority": False,
            "eyesPromotionEligible": False,
            "comparisonOnly": True,
            "humanReviewRequired": True,
            "productionActivation": False,
        }
        _write_json_create_only(output_receipt, receipt)
        created.append(output_receipt)
        verified = read_reviewed_runtime(
            base_runtime_dir=base_dir,
            iris_candidate_dir=candidate_dir,
            source_eye_appearance_dir=source_dir,
            reviewed_runtime_dir=output,
        )
        return verified
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        try:
            output.rmdir()
        except OSError:
            pass
        raise


def read_reviewed_runtime(
    *,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
) -> dict[str, Any]:
    base_dir = Path(base_runtime_dir).expanduser().resolve()
    candidate_dir = Path(iris_candidate_dir).expanduser().resolve()
    source_dir = Path(source_eye_appearance_dir).expanduser().resolve()
    reviewed_dir = Path(reviewed_runtime_dir).expanduser().resolve()
    base_receipt, base_vrm, base_receipt_path, eye_metadata = _base_runtime(base_dir)
    try:
        candidate = read_candidate(candidate_dir, source_eye_appearance_dir=source_dir)
        review = read_review(candidate_dir=candidate_dir, source_eye_appearance_dir=source_dir)
    except (SourceIrisIsolationError, SourceIrisIsolationReviewError) as exc:
        raise SourceIrisReviewRuntimeError(f"iris isolation authority failed: {exc}") from exc
    output_vrm = reviewed_dir / OUTPUT_VRM_NAME
    output_receipt = reviewed_dir / OUTPUT_RECEIPT_NAME
    if not output_vrm.is_file() or not output_receipt.is_file():
        raise SourceIrisReviewRuntimeError("reviewed iris runtime is missing its canonical VRM/receipt")
    value = _read_json(output_receipt, label="reviewed iris runtime receipt")
    required = {
        "format", "version", "bodyrigRevision", "baseRuntimeBodyrigRevision", "baseRuntimeReceiptSha256",
        "baseReviewVrmSha256", "reviewedVrmSha256", "irisCandidateSha256", "irisReviewSha256",
        "sourceEyeAppearanceReceiptSha256", "canonicalEyeBakeSha256", "sourceLeftEyeAppearanceSha256",
        "sourceRightEyeAppearanceSha256", "targetModelFamily", "runtimeBytesUnchanged", "sourceEyePixelsUnchanged",
        "embeddedEyeRuntimeStillReviewPending", "irisReviewOverlayApplied", "irisIdentityIsolated",
        "irisAppearanceStatus", "cornealMaterialStatus", "eyelashStatus", "eyeComponentAuthority",
        "eyesPromotionEligible", "comparisonOnly", "humanReviewRequired", "productionActivation",
    }
    if set(value) != required or value.get("format") != FORMAT or value.get("version") != VERSION:
        raise SourceIrisReviewRuntimeError("reviewed iris runtime receipt fields/format do not match v1")
    revision = _revision(value.get("bodyrigRevision"), label="reviewed runtime BodyRig revision")
    if candidate.get("bodyrigRevision") != revision or review.get("bodyrigRevision") != revision:
        raise SourceIrisReviewRuntimeError("reviewed runtime revision no longer matches iris candidate/review")
    exact = {
        "baseRuntimeBodyrigRevision": base_receipt["bodyrigRevision"],
        "baseRuntimeReceiptSha256": _sha256(base_receipt_path),
        "baseReviewVrmSha256": _sha256(base_vrm),
        "reviewedVrmSha256": _sha256(output_vrm),
        "irisCandidateSha256": _sha256(Path(str(candidate["candidatePath"])).resolve()),
        "irisReviewSha256": _sha256(Path(str(review["reviewPath"])).resolve()),
        "sourceEyeAppearanceReceiptSha256": candidate["sourceEyeAppearanceReceiptSha256"],
        "canonicalEyeBakeSha256": candidate["sourceCanonicalEyeBakeSha256"],
        "sourceLeftEyeAppearanceSha256": candidate["sourceLeftEyeAppearanceSha256"],
        "sourceRightEyeAppearanceSha256": candidate["sourceRightEyeAppearanceSha256"],
        "targetModelFamily": candidate["targetModelFamily"],
    }
    for field, expected in exact.items():
        if value.get(field) != expected:
            raise SourceIrisReviewRuntimeError(f"reviewed iris runtime no longer matches exact authority: {field}")
    if _sha256(output_vrm) != _sha256(base_vrm) or output_vrm.read_bytes() != base_vrm.read_bytes():
        raise SourceIrisReviewRuntimeError("reviewed runtime VRM bytes differ from base review runtime")
    if candidate.get("sourceEyeAppearanceReceiptSha256") != base_receipt["eyeAppearanceReceiptSha256"]:
        raise SourceIrisReviewRuntimeError("iris review source appearance differs from base runtime appearance")
    if candidate.get("sourceCanonicalEyeBakeSha256") != eye_metadata["canonicalEyeBakeSha256"]:
        raise SourceIrisReviewRuntimeError("iris review canonical source bake differs from embedded eye runtime")
    if (
        value.get("runtimeBytesUnchanged") is not True
        or value.get("sourceEyePixelsUnchanged") is not True
        or value.get("embeddedEyeRuntimeStillReviewPending") is not True
        or value.get("irisReviewOverlayApplied") is not True
        or value.get("irisIdentityIsolated") is not True
        or value.get("irisAppearanceStatus") != "source-isolated-review-pass"
        or value.get("cornealMaterialStatus") != "runtime-applied"
        or value.get("eyelashStatus") != "missing"
        or value.get("eyeComponentAuthority") is not False
        or value.get("eyesPromotionEligible") is not False
        or value.get("comparisonOnly") is not True
        or value.get("humanReviewRequired") is not True
        or value.get("productionActivation") is not False
    ):
        raise SourceIrisReviewRuntimeError("reviewed iris runtime crossed its narrow review-only authority boundary")
    return {**value, "reviewedVrmPath": str(output_vrm), "reviewReceiptPath": str(output_receipt)}
