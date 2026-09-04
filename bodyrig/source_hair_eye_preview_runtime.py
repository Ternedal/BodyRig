from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .avatar import AvatarError, validate_vrm1
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-source-hair-eye-preview-runtime"
VERSION = 1
SOURCE_FORMAT = "bodyrig-source-hair-eye-review-runtime"
SOURCE_VERSION = 1
RUNTIME_FORMAT = "bodyrig-runtime-assets"
RUNTIME_VERSION = 1


class SourceHairEyePreviewRuntimeError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceHairEyePreviewRuntimeError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SourceHairEyePreviewRuntimeError(f"{label} must be an object")
    return value


def _hex(value: Any, *, length: int, label: str) -> str:
    if not isinstance(value, str) or len(value) != length or any(ch not in "0123456789abcdef" for ch in value):
        raise SourceHairEyePreviewRuntimeError(f"{label} is invalid")
    return value


def _write_bytes(path: Path, raw: bytes) -> None:
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    raw = (json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    _write_bytes(path, raw)


def _validate_source_receipt(receipt: Mapping[str, Any]) -> None:
    required = {
        "format", "version", "bodyrigRevision", "bridgeScriptSha256", "bodyId",
        "packageSha256", "baseAvatarVrmSha256", "sourceHairBodyBindingSha256",
        "hairCandidateReceiptSha256", "eyeComponentReceiptSha256",
        "eyeAppearanceReceiptSha256", "reviewVrmSha256", "bridgeResultSha256",
        "targetModelFamily", "hairMeshIndex", "eyeMeshIndex", "leftEyeFaceCount",
        "rightEyeFaceCount", "sourceHairRuntimeApplied", "sourceEyeSurfaceApplied",
        "irisIdentityIsolated", "irisAppearanceStatus", "cornealMaterialStatus",
        "eyelashStatus", "runtimeIntegrationStatus", "physicalSilhouetteReviewRequired",
        "physicalFaceCloseupReviewRequired", "comparisonOnly", "humanReviewRequired",
        "hairComponentAuthority", "eyeComponentAuthority", "productionActivation",
    }
    if set(receipt) != required or receipt.get("format") != SOURCE_FORMAT or receipt.get("version") != SOURCE_VERSION:
        raise SourceHairEyePreviewRuntimeError("source hair+eye review receipt fields/format do not match v1")
    _hex(receipt.get("bodyrigRevision"), length=40, label="source review BodyRig revision")
    for field in (
        "bridgeScriptSha256", "packageSha256", "baseAvatarVrmSha256",
        "sourceHairBodyBindingSha256", "hairCandidateReceiptSha256",
        "eyeComponentReceiptSha256", "eyeAppearanceReceiptSha256",
        "reviewVrmSha256", "bridgeResultSha256",
    ):
        _hex(receipt.get(field), length=64, label=f"source review {field}")
    if receipt.get("targetModelFamily") not in {"female", "male", "neutral"}:
        raise SourceHairEyePreviewRuntimeError("source review target model family is invalid")
    if (
        receipt.get("sourceHairRuntimeApplied") is not True
        or receipt.get("sourceEyeSurfaceApplied") is not True
        or receipt.get("irisIdentityIsolated") is not False
        or receipt.get("irisAppearanceStatus") != "review-pending"
        or receipt.get("cornealMaterialStatus") != "runtime-applied"
        or receipt.get("runtimeIntegrationStatus") != "hair-and-eyes-review-artifact-ready"
        or receipt.get("physicalSilhouetteReviewRequired") is not True
        or receipt.get("physicalFaceCloseupReviewRequired") is not True
        or receipt.get("comparisonOnly") is not True
        or receipt.get("humanReviewRequired") is not True
        or receipt.get("hairComponentAuthority") is not False
        or receipt.get("eyeComponentAuthority") is not False
        or receipt.get("productionActivation") is not False
    ):
        raise SourceHairEyePreviewRuntimeError("source hair+eye review receipt is not valid non-activating review authority")


def materialize(
    *,
    package_path: str | Path,
    review_runtime_dir: str | Path,
    destination: str | Path,
) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    review_root = Path(review_runtime_dir).expanduser().resolve()
    target = Path(destination).expanduser().resolve()
    if not package.is_file():
        raise SourceHairEyePreviewRuntimeError(f"candidate package not found: {package}")
    if not review_root.is_dir():
        raise SourceHairEyePreviewRuntimeError(f"hair+eye review runtime directory not found: {review_root}")
    if target.exists():
        raise SourceHairEyePreviewRuntimeError(f"preview runtime destination already exists: {target}")

    source_receipt_path = review_root / "source-hair-eye-review-runtime.json"
    review_vrm_path = review_root / "source-hair-eye-review.vrm"
    if not source_receipt_path.is_file() or not review_vrm_path.is_file():
        raise SourceHairEyePreviewRuntimeError("hair+eye review runtime lacks its canonical receipt/VRM pair")
    source_receipt = _read_json(source_receipt_path, label="hair+eye review runtime receipt")
    _validate_source_receipt(source_receipt)

    try:
        validated = validate_package(package)
    except MRBodyError as exc:
        raise SourceHairEyePreviewRuntimeError(f"candidate package is invalid: {exc}") from exc
    package_sha = _sha256(package)
    if source_receipt["packageSha256"] != package_sha:
        raise SourceHairEyePreviewRuntimeError("hair+eye review runtime targets different package bytes")
    if source_receipt["bodyId"] != validated.manifest["id"]:
        raise SourceHairEyePreviewRuntimeError("hair+eye review runtime targets different body identity")
    review_vrm = review_vrm_path.read_bytes()
    review_vrm_sha = _sha256_bytes(review_vrm)
    if source_receipt["reviewVrmSha256"] != review_vrm_sha:
        raise SourceHairEyePreviewRuntimeError("hair+eye review VRM bytes changed after runtime finalization")
    try:
        validate_vrm1(review_vrm)
    except AvatarError as exc:
        raise SourceHairEyePreviewRuntimeError(f"hair+eye review artifact is not valid VRM 1.0: {exc}") from exc

    try:
        with zipfile.ZipFile(package, "r") as archive:
            bodyprint = archive.read("bodyprint.json")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise SourceHairEyePreviewRuntimeError("candidate package bodyprint.json is unavailable") from exc
    bodyprint_sha = _sha256_bytes(bodyprint)

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = Path(tempfile.mkdtemp(prefix=target.name + ".", suffix=".tmp", dir=target.parent))
    try:
        avatar_path = temp / "avatar.vrm"
        bodyprint_path = temp / "bodyprint.json"
        manifest_path = temp / "runtime-manifest.json"
        authority_path = temp / "review-runtime-authority.json"
        _write_bytes(avatar_path, review_vrm)
        _write_bytes(bodyprint_path, bodyprint)
        runtime_manifest = {
            "format": RUNTIME_FORMAT,
            "version": RUNTIME_VERSION,
            "body_id": validated.manifest["id"],
            "body_name": validated.manifest["name"],
            "package_sha256": package_sha,
            "avatar": "avatar.vrm",
            "avatar_sha256": review_vrm_sha,
            "bodyprint": "bodyprint.json",
            "bodyprint_sha256": bodyprint_sha,
            "payloads": ["avatar.vrm", "bodyprint.json"],
        }
        _write_json(manifest_path, runtime_manifest)
        runtime_manifest_sha = _sha256(manifest_path)
        authority = {
            "format": FORMAT,
            "version": VERSION,
            "bodyrigRevision": source_receipt["bodyrigRevision"],
            "bodyId": validated.manifest["id"],
            "packageSha256": package_sha,
            "sourceReviewReceiptSha256": _sha256(source_receipt_path),
            "reviewVrmSha256": review_vrm_sha,
            "bodyprintSha256": bodyprint_sha,
            "runtimeManifestSha256": runtime_manifest_sha,
            "sourceHairRuntimeApplied": True,
            "sourceEyeSurfaceApplied": True,
            "cornealMaterialStatus": "runtime-applied",
            "physicalSilhouetteReviewRequired": True,
            "physicalFaceCloseupReviewRequired": True,
            "comparisonOnly": True,
            "humanReviewRequired": True,
            "physicalAcceptanceAuthority": False,
            "productionActivation": False,
        }
        _write_json(authority_path, authority)
        os.replace(temp, target)
    except Exception:
        shutil.rmtree(temp, ignore_errors=True)
        raise

    return {
        "ok": True,
        "runtime_manifest": str(target / "runtime-manifest.json"),
        "review_runtime_authority": str(target / "review-runtime-authority.json"),
        "package_sha256": package_sha,
        "review_vrm_sha256": review_vrm_sha,
        "runtime_manifest_sha256": runtime_manifest_sha,
        "comparison_only": True,
        "production_activation": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize a renderer-compatible, review-only source hair+eye runtime.")
    parser.add_argument("--package", required=True)
    parser.add_argument("--review-runtime-dir", required=True)
    parser.add_argument("--destination", required=True)
    args = parser.parse_args(argv)
    try:
        result = materialize(
            package_path=args.package,
            review_runtime_dir=args.review_runtime_dir,
            destination=args.destination,
        )
        print(json.dumps(result, separators=(",", ":"), allow_nan=False))
        return 0
    except (SourceHairEyePreviewRuntimeError, OSError) as exc:
        print(f"BodyRig hair+eye preview runtime: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    import sys
    raise SystemExit(main())
