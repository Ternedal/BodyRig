from __future__ import annotations

import hashlib
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .bridges.sith_pbr_material import PbrMaterialError, _read_glb
from .high_fidelity_eye_runtime_fingerprint import (
    HighFidelityEyeRuntimeFingerprintError,
    read_fingerprint,
    semantic_eye_runtime_fingerprint,
)
from .package import MRBodyError, validate_package
from .source_iris_review_runtime import SourceIrisReviewRuntimeError, _base_runtime

FORMAT = "bodyrig-high-fidelity-eye-runtime-rebuild"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-eye-runtime-rebuild-v1"
PREPARATION_FORMAT = "bodyrig-high-fidelity-eye-runtime-rebuild-preparation"
PREPARATION_VERSION = 1
PREPARATION_NAME = "eye-only-rebuild-preparation.json"
BASE_AVATAR_NAME = "base-avatar.vrm"
BRIDGE_FORMAT = "bodyrig-source-eye-review-bridge"
BRIDGE_VERSION = 1
BRIDGE_RESULT_NAME = "source-eye-review-bridge.json"
REVIEW_VRM_NAME = "source-eye-review.vrm"
RECEIPT_NAME = "source-eye-runtime-rebuild.json"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
JOB_RE = re.compile(r"^hfpreview-[0-9a-f]{32}$")


class HighFidelityEyeRuntimeRebuildError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(clean):
        raise HighFidelityEyeRuntimeRebuildError(f"{label} is not a canonical SHA-256")
    return clean


def _revision(value: Any, *, label: str = "BodyRig revision") -> str:
    clean = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(clean):
        raise HighFidelityEyeRuntimeRebuildError(f"{label} is not a canonical Git SHA")
    return clean


def _job(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not JOB_RE.fullmatch(clean):
        raise HighFidelityEyeRuntimeRebuildError("high-fidelity preview job id is not canonical")
    return clean


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityEyeRuntimeRebuildError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise HighFidelityEyeRuntimeRebuildError(f"{label} must be a JSON object")
    return value


def _write_json_create_only(path: Path, value: Mapping[str, Any]) -> None:
    raw = (json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise HighFidelityEyeRuntimeRebuildError(f"refusing to overwrite eye runtime rebuild authority: {path}") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _fingerprint_authority(
    preview_job_id: str,
    *,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
) -> tuple[dict[str, Any], Path]:
    try:
        value = read_fingerprint(
            preview_job_id,
            base_runtime_dir=base_runtime_dir,
            iris_candidate_dir=iris_candidate_dir,
            source_eye_appearance_dir=source_eye_appearance_dir,
            reviewed_runtime_dir=reviewed_runtime_dir,
        )
    except HighFidelityEyeRuntimeFingerprintError as exc:
        raise HighFidelityEyeRuntimeRebuildError(f"reviewed eye fingerprint authority failed: {exc}") from exc
    path = Path(str(value.get("fingerprintPath") or "")).expanduser().resolve()
    if not path.is_file():
        raise HighFidelityEyeRuntimeRebuildError("reviewed eye fingerprint receipt disappeared after validation")
    if (
        value.get("eyesPromotionEligibilityVerified") is not True
        or value.get("eyeComponentAuthority") is not False
        or value.get("packageMutationPerformed") is not False
        or value.get("eyesPromoted") is not False
        or value.get("productionActivation") is not False
    ):
        raise HighFidelityEyeRuntimeRebuildError("reviewed eye fingerprint crossed its non-materializing boundary")
    return value, path


def _package_avatar(package_path: Path) -> tuple[bytes, str]:
    try:
        validated = validate_package(package_path)
    except MRBodyError as exc:
        raise HighFidelityEyeRuntimeRebuildError(f"candidate package is invalid: {exc}") from exc
    try:
        with zipfile.ZipFile(package_path, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityEyeRuntimeRebuildError("candidate package has no readable avatar.vrm") from exc
    return avatar, str(validated.manifest["id"])


def prepare_rebuild(
    preview_job_id: str,
    *,
    package_path: str | Path,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    staging_dir: str | Path,
    bodyrig_revision: str,
) -> dict[str, Any]:
    job_id = _job(preview_job_id)
    revision = _revision(bodyrig_revision, label="rebuild BodyRig revision")
    package = Path(package_path).expanduser().resolve()
    staging = Path(staging_dir).expanduser().resolve()
    if not package.is_file():
        raise HighFidelityEyeRuntimeRebuildError(f"candidate package is missing: {package}")
    if not staging.is_dir():
        raise HighFidelityEyeRuntimeRebuildError("eye-only rebuild staging directory must already exist")
    prep_path = staging / PREPARATION_NAME
    avatar_path = staging / BASE_AVATAR_NAME
    if prep_path.exists() or avatar_path.exists():
        raise HighFidelityEyeRuntimeRebuildError("eye-only rebuild preparation is create-only")

    fingerprint, fingerprint_file = _fingerprint_authority(
        job_id,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
    )
    package_sha = _sha256_file(package)
    if package_sha != fingerprint.get("candidatePackageSha256"):
        raise HighFidelityEyeRuntimeRebuildError("candidate package differs from reviewed eye fingerprint authority")
    avatar, body_id = _package_avatar(package)
    if body_id != fingerprint.get("canonicalBodyId"):
        raise HighFidelityEyeRuntimeRebuildError("candidate package canonical body id differs from eye fingerprint authority")

    try:
        base_receipt, _base_review_vrm, base_receipt_path, _eye_metadata = _base_runtime(Path(base_runtime_dir).expanduser().resolve())
    except SourceIrisReviewRuntimeError as exc:
        raise HighFidelityEyeRuntimeRebuildError(f"base runtime authority failed: {exc}") from exc
    if base_receipt.get("packageSha256") != package_sha or base_receipt.get("bodyId") != body_id:
        raise HighFidelityEyeRuntimeRebuildError("base runtime no longer belongs to the exact candidate package")
    avatar_sha = _sha256_bytes(avatar)
    if avatar_sha != base_receipt.get("baseAvatarVrmSha256"):
        raise HighFidelityEyeRuntimeRebuildError("candidate package avatar differs from the exact base avatar used for reviewed runtime")

    created: list[Path] = []
    try:
        avatar_path.write_bytes(avatar)
        created.append(avatar_path)
        receipt = {
            "format": PREPARATION_FORMAT,
            "version": PREPARATION_VERSION,
            "policyRevision": POLICY_REVISION,
            "bodyrigRevision": revision,
            "previewJobId": job_id,
            "canonicalBodyId": body_id,
            "candidatePackageSha256": package_sha,
            "baseAvatarVrmSha256": avatar_sha,
            "baseRuntimeReceiptSha256": _sha256_file(base_receipt_path),
            "sourceFingerprintReceiptSha256": _sha256_file(fingerprint_file),
            "sourceFingerprintSha256": _sha(fingerprint["fingerprintSha256"], label="source eye fingerprint SHA"),
            "reviewVrmSha256": _sha(fingerprint["reviewVrmSha256"], label="review VRM SHA"),
            "eyeComponentAuthority": False,
            "packageMutationPerformed": False,
            "productionActivation": False,
        }
        _write_json_create_only(prep_path, receipt)
        created.append(prep_path)
        verified = read_preparation(
            job_id,
            package_path=package,
            base_runtime_dir=base_runtime_dir,
            iris_candidate_dir=iris_candidate_dir,
            source_eye_appearance_dir=source_eye_appearance_dir,
            reviewed_runtime_dir=reviewed_runtime_dir,
            staging_dir=staging,
        )
        return {**verified, "baseAvatarPath": str(avatar_path), "preparationPath": str(prep_path)}
    except Exception:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise


def read_preparation(
    preview_job_id: str,
    *,
    package_path: str | Path,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    staging_dir: str | Path,
) -> dict[str, Any]:
    job_id = _job(preview_job_id)
    package = Path(package_path).expanduser().resolve()
    staging = Path(staging_dir).expanduser().resolve()
    prep_path = staging / PREPARATION_NAME
    avatar_path = staging / BASE_AVATAR_NAME
    if not prep_path.is_file() or not avatar_path.is_file():
        raise HighFidelityEyeRuntimeRebuildError("eye-only rebuild preparation artifacts are missing")
    value = _read_json(prep_path, label="eye-only rebuild preparation")
    required = {
        "format", "version", "policyRevision", "bodyrigRevision", "previewJobId", "canonicalBodyId",
        "candidatePackageSha256", "baseAvatarVrmSha256", "baseRuntimeReceiptSha256",
        "sourceFingerprintReceiptSha256", "sourceFingerprintSha256", "reviewVrmSha256",
        "eyeComponentAuthority", "packageMutationPerformed", "productionActivation",
    }
    if set(value) != required or value.get("format") != PREPARATION_FORMAT or value.get("version") != PREPARATION_VERSION or value.get("policyRevision") != POLICY_REVISION:
        raise HighFidelityEyeRuntimeRebuildError("eye-only rebuild preparation fields/format are invalid")
    _revision(value.get("bodyrigRevision"), label="preparation BodyRig revision")
    fingerprint, fingerprint_file = _fingerprint_authority(
        job_id,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
    )
    package_sha = _sha256_file(package)
    avatar, body_id = _package_avatar(package)
    try:
        base_receipt, _base_review_vrm, base_receipt_path, _eye_metadata = _base_runtime(Path(base_runtime_dir).expanduser().resolve())
    except SourceIrisReviewRuntimeError as exc:
        raise HighFidelityEyeRuntimeRebuildError(f"base runtime authority failed: {exc}") from exc
    exact = {
        "previewJobId": job_id,
        "canonicalBodyId": body_id,
        "candidatePackageSha256": package_sha,
        "baseAvatarVrmSha256": _sha256_bytes(avatar),
        "baseRuntimeReceiptSha256": _sha256_file(base_receipt_path),
        "sourceFingerprintReceiptSha256": _sha256_file(fingerprint_file),
        "sourceFingerprintSha256": fingerprint["fingerprintSha256"],
        "reviewVrmSha256": fingerprint["reviewVrmSha256"],
    }
    for field, expected in exact.items():
        if str(value.get(field) or "") != str(expected or ""):
            raise HighFidelityEyeRuntimeRebuildError(f"eye-only rebuild preparation no longer matches exact authority: {field}")
    if value["candidatePackageSha256"] != fingerprint.get("candidatePackageSha256") or value["canonicalBodyId"] != fingerprint.get("canonicalBodyId"):
        raise HighFidelityEyeRuntimeRebuildError("preparation candidate identity differs from reviewed eye fingerprint")
    if base_receipt.get("packageSha256") != package_sha or base_receipt.get("baseAvatarVrmSha256") != value["baseAvatarVrmSha256"]:
        raise HighFidelityEyeRuntimeRebuildError("preparation base runtime authority changed")
    if _sha256_file(avatar_path) != value["baseAvatarVrmSha256"] or avatar_path.read_bytes() != avatar:
        raise HighFidelityEyeRuntimeRebuildError("prepared base avatar bytes changed")
    if value.get("eyeComponentAuthority") is not False or value.get("packageMutationPerformed") is not False or value.get("productionActivation") is not False:
        raise HighFidelityEyeRuntimeRebuildError("eye-only rebuild preparation crossed authority boundary")
    return {**value, "baseAvatarPath": str(avatar_path), "preparationPath": str(prep_path)}


def _bridge(path: Path, *, vrm_path: Path, preparation: Mapping[str, Any], source_fingerprint: Mapping[str, Any]) -> dict[str, Any]:
    value = _read_json(path, label="eye-only bridge result")
    required = {
        "format", "version", "baseAvatarVrmSha256", "eyeComponentReceiptSha256",
        "eyeAppearanceReceiptSha256", "canonicalEyeBakeSha256", "eyeMeshIndex", "reviewVrmSha256",
        "targetModelFamily", "leftEyeFaceCount", "rightEyeFaceCount", "leftEyeRuntimeVertices",
        "rightEyeRuntimeVertices", "sourceHairRuntimeApplied", "sourceEyeSurfaceApplied",
        "irisIdentityIsolated", "irisAppearanceStatus", "cornealMaterialStatus", "eyelashStatus",
        "comparisonOnly", "humanReviewRequired", "eyeComponentAuthority", "productionActivation",
    }
    if set(value) != required or value.get("format") != BRIDGE_FORMAT or value.get("version") != BRIDGE_VERSION:
        raise HighFidelityEyeRuntimeRebuildError("eye-only bridge fields/format do not match v1")
    for field in ("baseAvatarVrmSha256", "eyeComponentReceiptSha256", "eyeAppearanceReceiptSha256", "canonicalEyeBakeSha256", "reviewVrmSha256"):
        _sha(value.get(field), label=f"eye-only bridge {field}")
    if value.get("baseAvatarVrmSha256") != preparation.get("baseAvatarVrmSha256"):
        raise HighFidelityEyeRuntimeRebuildError("eye-only bridge used a different base avatar")
    if value.get("reviewVrmSha256") != _sha256_file(vrm_path):
        raise HighFidelityEyeRuntimeRebuildError("eye-only bridge no longer binds exact rebuilt VRM bytes")
    payload = source_fingerprint.get("fingerprint")
    metadata = payload.get("eyeMetadata") if isinstance(payload, Mapping) else None
    if not isinstance(metadata, Mapping):
        raise HighFidelityEyeRuntimeRebuildError("source fingerprint lacks canonical eye metadata")
    if value.get("eyeComponentReceiptSha256") != metadata.get("eyeComponentReceiptSha256"):
        raise HighFidelityEyeRuntimeRebuildError("eye-only bridge geometry receipt differs from reviewed fingerprint")
    if value.get("eyeAppearanceReceiptSha256") != metadata.get("eyeAppearanceReceiptSha256"):
        raise HighFidelityEyeRuntimeRebuildError("eye-only bridge appearance receipt differs from reviewed fingerprint")
    if value.get("canonicalEyeBakeSha256") != metadata.get("canonicalEyeBakeSha256"):
        raise HighFidelityEyeRuntimeRebuildError("eye-only bridge source bake differs from reviewed fingerprint")
    if value.get("targetModelFamily") != metadata.get("targetModelFamily"):
        raise HighFidelityEyeRuntimeRebuildError("eye-only bridge target family differs from reviewed fingerprint")
    for field in ("eyeMeshIndex", "leftEyeFaceCount", "rightEyeFaceCount", "leftEyeRuntimeVertices", "rightEyeRuntimeVertices"):
        item = value.get(field)
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise HighFidelityEyeRuntimeRebuildError(f"eye-only bridge {field} is invalid")
    if (
        value.get("sourceHairRuntimeApplied") is not False
        or value.get("sourceEyeSurfaceApplied") is not True
        or value.get("irisIdentityIsolated") is not False
        or value.get("irisAppearanceStatus") != "review-pending"
        or value.get("cornealMaterialStatus") != "runtime-applied"
        or value.get("eyelashStatus") != "missing"
        or value.get("comparisonOnly") is not True
        or value.get("humanReviewRequired") is not True
        or value.get("eyeComponentAuthority") is not False
        or value.get("productionActivation") is not False
    ):
        raise HighFidelityEyeRuntimeRebuildError("eye-only bridge crossed its review-only authority boundary")
    return value


def _assert_no_hair_runtime(vrm_bytes: bytes) -> None:
    try:
        document, _binary = _read_glb(vrm_bytes)
    except PbrMaterialError as exc:
        raise HighFidelityEyeRuntimeRebuildError(f"rebuilt eye-only VRM is invalid GLB: {exc}") from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict) or "eyeReviewRuntime" not in bodyrig:
        raise HighFidelityEyeRuntimeRebuildError("rebuilt eye-only VRM lacks canonical eye runtime metadata")
    if "hairReviewRuntime" in bodyrig:
        raise HighFidelityEyeRuntimeRebuildError("rebuilt eye-only VRM imported hair runtime metadata")
    nodes = document.get("nodes")
    if not isinstance(nodes, list):
        raise HighFidelityEyeRuntimeRebuildError("rebuilt eye-only VRM node array is invalid")
    if any(isinstance(item, dict) and item.get("name") == "BodyRigSourceHairReview" for item in nodes):
        raise HighFidelityEyeRuntimeRebuildError("rebuilt eye-only VRM imported source-hair runtime geometry")


def finalize_rebuild(
    preview_job_id: str,
    *,
    package_path: str | Path,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    staging_dir: str | Path,
    bodyrig_revision: str,
    bridge_script_sha256: str,
) -> dict[str, Any]:
    revision = _revision(bodyrig_revision, label="rebuild BodyRig revision")
    bridge_script_sha = _sha(bridge_script_sha256, label="eye-only bridge script SHA")
    staging = Path(staging_dir).expanduser().resolve()
    preparation = read_preparation(
        preview_job_id,
        package_path=package_path,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
        staging_dir=staging,
    )
    if preparation.get("bodyrigRevision") != revision:
        raise HighFidelityEyeRuntimeRebuildError("eye-only rebuild preparation revision differs from finalizer checkout")
    source_fingerprint, fingerprint_file = _fingerprint_authority(
        preview_job_id,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
    )
    vrm_path = staging / REVIEW_VRM_NAME
    bridge_path = staging / BRIDGE_RESULT_NAME
    receipt_path = staging / RECEIPT_NAME
    if not vrm_path.is_file() or not bridge_path.is_file():
        raise HighFidelityEyeRuntimeRebuildError("eye-only bridge output is missing")
    if receipt_path.exists():
        raise HighFidelityEyeRuntimeRebuildError("eye-only runtime rebuild receipt is create-only")
    bridge = _bridge(bridge_path, vrm_path=vrm_path, preparation=preparation, source_fingerprint=source_fingerprint)
    vrm_bytes = vrm_path.read_bytes()
    _assert_no_hair_runtime(vrm_bytes)
    rebuilt = semantic_eye_runtime_fingerprint(vrm_bytes)
    source_sha = _sha(source_fingerprint["fingerprintSha256"], label="source eye fingerprint SHA")
    if rebuilt.get("fingerprintSha256") != source_sha or rebuilt.get("payload") != source_fingerprint.get("fingerprint"):
        raise HighFidelityEyeRuntimeRebuildError("eye-only runtime semantic fingerprint differs from the reviewed eye stage")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policyRevision": POLICY_REVISION,
        "bodyrigRevision": revision,
        "previewJobId": _job(preview_job_id),
        "canonicalBodyId": str(preparation["canonicalBodyId"]),
        "candidatePackageSha256": _sha(preparation["candidatePackageSha256"], label="candidate package SHA"),
        "preparationSha256": _sha256_file(staging / PREPARATION_NAME),
        "sourceFingerprintReceiptSha256": _sha256_file(fingerprint_file),
        "sourceFingerprintSha256": source_sha,
        "bridgeScriptSha256": bridge_script_sha,
        "bridgeResultSha256": _sha256_file(bridge_path),
        "baseAvatarVrmSha256": _sha(preparation["baseAvatarVrmSha256"], label="base avatar SHA"),
        "rebuiltReviewVrmSha256": _sha256_file(vrm_path),
        "rebuiltFingerprintSha256": rebuilt["fingerprintSha256"],
        "fingerprintMatch": True,
        "sourceHairRuntimeImported": False,
        "eyeOnlyRuntimeVerified": True,
        "eyeComponentAuthority": False,
        "packageMutationPerformed": False,
        "eyesPromoted": False,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    _write_json_create_only(receipt_path, receipt)
    try:
        verified = read_rebuild(
            preview_job_id,
            package_path=package_path,
            base_runtime_dir=base_runtime_dir,
            iris_candidate_dir=iris_candidate_dir,
            source_eye_appearance_dir=source_eye_appearance_dir,
            reviewed_runtime_dir=reviewed_runtime_dir,
            staging_dir=staging,
            bridge_script_sha256=bridge_script_sha,
        )
    except Exception:
        receipt_path.unlink(missing_ok=True)
        raise
    return {**verified, "rebuildReceiptPath": str(receipt_path), "rebuiltVrmPath": str(vrm_path)}


def read_rebuild(
    preview_job_id: str,
    *,
    package_path: str | Path,
    base_runtime_dir: str | Path,
    iris_candidate_dir: str | Path,
    source_eye_appearance_dir: str | Path,
    reviewed_runtime_dir: str | Path,
    staging_dir: str | Path,
    bridge_script_sha256: str,
) -> dict[str, Any]:
    staging = Path(staging_dir).expanduser().resolve()
    preparation = read_preparation(
        preview_job_id,
        package_path=package_path,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
        staging_dir=staging,
    )
    source_fingerprint, fingerprint_file = _fingerprint_authority(
        preview_job_id,
        base_runtime_dir=base_runtime_dir,
        iris_candidate_dir=iris_candidate_dir,
        source_eye_appearance_dir=source_eye_appearance_dir,
        reviewed_runtime_dir=reviewed_runtime_dir,
    )
    vrm_path = staging / REVIEW_VRM_NAME
    bridge_path = staging / BRIDGE_RESULT_NAME
    receipt_path = staging / RECEIPT_NAME
    if not vrm_path.is_file() or not bridge_path.is_file() or not receipt_path.is_file():
        raise HighFidelityEyeRuntimeRebuildError("eye-only runtime rebuild artifacts are incomplete")
    bridge = _bridge(bridge_path, vrm_path=vrm_path, preparation=preparation, source_fingerprint=source_fingerprint)
    _assert_no_hair_runtime(vrm_path.read_bytes())
    rebuilt = semantic_eye_runtime_fingerprint(vrm_path.read_bytes())
    source_sha = _sha(source_fingerprint["fingerprintSha256"], label="source eye fingerprint SHA")
    if rebuilt.get("fingerprintSha256") != source_sha or rebuilt.get("payload") != source_fingerprint.get("fingerprint"):
        raise HighFidelityEyeRuntimeRebuildError("rebuilt eye-only runtime no longer matches reviewed semantic fingerprint")
    value = _read_json(receipt_path, label="eye-only runtime rebuild receipt")
    required = {
        "format", "version", "policyRevision", "bodyrigRevision", "previewJobId", "canonicalBodyId",
        "candidatePackageSha256", "preparationSha256", "sourceFingerprintReceiptSha256",
        "sourceFingerprintSha256", "bridgeScriptSha256", "bridgeResultSha256", "baseAvatarVrmSha256",
        "rebuiltReviewVrmSha256", "rebuiltFingerprintSha256", "fingerprintMatch",
        "sourceHairRuntimeImported", "eyeOnlyRuntimeVerified", "eyeComponentAuthority",
        "packageMutationPerformed", "eyesPromoted", "humanReviewRequired", "productionActivation",
    }
    if set(value) != required or value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policyRevision") != POLICY_REVISION:
        raise HighFidelityEyeRuntimeRebuildError("eye-only runtime rebuild receipt fields/format are invalid")
    exact = {
        "previewJobId": _job(preview_job_id),
        "canonicalBodyId": preparation["canonicalBodyId"],
        "candidatePackageSha256": preparation["candidatePackageSha256"],
        "preparationSha256": _sha256_file(staging / PREPARATION_NAME),
        "sourceFingerprintReceiptSha256": _sha256_file(fingerprint_file),
        "sourceFingerprintSha256": source_sha,
        "bridgeScriptSha256": _sha(bridge_script_sha256, label="eye-only bridge script SHA"),
        "bridgeResultSha256": _sha256_file(bridge_path),
        "baseAvatarVrmSha256": preparation["baseAvatarVrmSha256"],
        "rebuiltReviewVrmSha256": _sha256_file(vrm_path),
        "rebuiltFingerprintSha256": rebuilt["fingerprintSha256"],
    }
    for field, expected in exact.items():
        if str(value.get(field) or "") != str(expected or ""):
            raise HighFidelityEyeRuntimeRebuildError(f"eye-only runtime rebuild no longer matches exact authority: {field}")
    if bridge.get("reviewVrmSha256") != value["rebuiltReviewVrmSha256"]:
        raise HighFidelityEyeRuntimeRebuildError("eye-only bridge/result receipt VRM hashes disagree")
    if (
        value.get("fingerprintMatch") is not True
        or value.get("sourceHairRuntimeImported") is not False
        or value.get("eyeOnlyRuntimeVerified") is not True
        or value.get("eyeComponentAuthority") is not False
        or value.get("packageMutationPerformed") is not False
        or value.get("eyesPromoted") is not False
        or value.get("humanReviewRequired") is not True
        or value.get("productionActivation") is not False
    ):
        raise HighFidelityEyeRuntimeRebuildError("eye-only runtime rebuild crossed its non-materializing authority boundary")
    _revision(value.get("bodyrigRevision"), label="rebuild BodyRig revision")
    return {**value, "rebuildReceiptPath": str(receipt_path), "rebuiltVrmPath": str(vrm_path)}
