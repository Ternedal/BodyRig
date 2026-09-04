from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path
from typing import Any

from .high_fidelity_face_secondary_runtime import (
    RECEIPT_NAME as RUNTIME_RECEIPT_NAME,
    REVIEW_VRM_NAME,
    HighFidelityFaceSecondaryRuntimeError,
    read_runtime,
)
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-high-fidelity-face-secondary-preview-preparation"
VERSION = 1
COMPARISON_PACKAGE_NAME = "face-secondary-review-comparison.mrbody"
PREPARATION_NAME = "face-secondary-preview-preparation.json"


class HighFidelityFaceSecondaryPreviewError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _write_package(source: Path, destination: Path, *, avatar_vrm: bytes) -> None:
    try:
        with zipfile.ZipFile(source, "r") as archive:
            order = [info.filename for info in archive.infolist()]
            payload = {name: archive.read(name) for name in order}
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HighFidelityFaceSecondaryPreviewError("could not read source package for comparison materialization") from exc
    if "avatar.vrm" not in payload or "checksums.json" not in payload:
        raise HighFidelityFaceSecondaryPreviewError("source package lacks canonical avatar/checksum files")
    payload["avatar.vrm"] = avatar_vrm
    checksum_names = set(order) - {"manifest.json", "checksums.json"}
    payload["checksums.json"] = json.dumps(
        {name: _sha256_bytes(payload[name]) for name in checksum_names},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    try:
        with zipfile.ZipFile(destination, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in order:
                archive.writestr(name, payload[name])
    except FileExistsError as exc:
        raise HighFidelityFaceSecondaryPreviewError("comparison package is create-only") from exc
    except OSError as exc:
        raise HighFidelityFaceSecondaryPreviewError("could not write comparison package") from exc


def prepare(package_path: str | Path, runtime_dir: str | Path, output_dir: str | Path, *, bodyrig_revision: str) -> dict[str, Any]:
    source = Path(package_path).expanduser().resolve()
    runtime_root = Path(runtime_dir).expanduser().resolve()
    root = Path(output_dir).expanduser().resolve()
    if root.exists():
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview preparation is create-only")
    if not isinstance(bodyrig_revision, str) or len(bodyrig_revision) != 40 or any(ch not in "0123456789abcdef" for ch in bodyrig_revision):
        raise HighFidelityFaceSecondaryPreviewError("BodyRig revision is not canonical")
    if not source.is_file():
        raise HighFidelityFaceSecondaryPreviewError("source promoted package is missing")
    try:
        validated = validate_package(source)
        runtime = read_runtime(runtime_root)
    except (MRBodyError, HighFidelityFaceSecondaryRuntimeError) as exc:
        raise HighFidelityFaceSecondaryPreviewError(str(exc)) from exc
    source_sha = _sha256_file(source)
    if runtime.get("sourcePackageSha256") != source_sha:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary runtime targets different package bytes")
    if runtime.get("canonicalBodyId") != validated.manifest["id"]:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary runtime targets different body identity")
    if runtime.get("bodyrigRevision") != bodyrig_revision:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary runtime was built by a different BodyRig revision")
    vrm_path = Path(runtime["reviewVrmPath"]).resolve()
    runtime_receipt_path = Path(runtime["receiptPath"]).resolve()
    review_vrm = vrm_path.read_bytes()
    if runtime.get("reviewVrmSha256") != _sha256_bytes(review_vrm):
        raise HighFidelityFaceSecondaryPreviewError("face-secondary review VRM changed after runtime validation")

    root.mkdir(parents=True)
    comparison = root / COMPARISON_PACKAGE_NAME
    preparation = root / PREPARATION_NAME
    created = False
    try:
        _write_package(source, comparison, avatar_vrm=review_vrm)
        created = True
        try:
            comparison_validated = validate_package(comparison)
        except MRBodyError as exc:
            raise HighFidelityFaceSecondaryPreviewError(f"comparison package failed strict validation: {exc}") from exc
        if comparison_validated.manifest["id"] != validated.manifest["id"]:
            raise HighFidelityFaceSecondaryPreviewError("comparison package changed canonical body identity")
        value = {
            "format": FORMAT,
            "version": VERSION,
            "bodyrigRevision": bodyrig_revision,
            "canonicalBodyId": str(validated.manifest["id"]),
            "sourcePackageSha256": source_sha,
            "sourceRuntimeReceiptSha256": _sha256_file(runtime_receipt_path),
            "sourceReviewVrmSha256": _sha256_file(vrm_path),
            "comparisonPackageSha256": _sha256_file(comparison),
            "comparisonPackageName": COMPARISON_PACKAGE_NAME,
            "comparisonOnly": True,
            "physicalAcceptanceAuthority": False,
            "humanReviewRequired": True,
            "packagePromotionAuthority": False,
            "productionActivation": False,
        }
        with preparation.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
        return {**value, "comparisonPackagePath": str(comparison), "preparationPath": str(preparation)}
    except Exception:
        if created:
            comparison.unlink(missing_ok=True)
        preparation.unlink(missing_ok=True)
        try:
            root.rmdir()
        except OSError:
            pass
        raise


def read_preparation(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    preparation = root / PREPARATION_NAME
    comparison = root / COMPARISON_PACKAGE_NAME
    if not preparation.is_file() or not comparison.is_file():
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview preparation evidence is missing")
    try:
        value = json.loads(preparation.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview preparation is unreadable") from exc
    if not isinstance(value, dict) or value.get("format") != FORMAT or value.get("version") != VERSION:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview preparation format/version mismatch")
    if value.get("comparisonPackageName") != COMPARISON_PACKAGE_NAME or value.get("comparisonPackageSha256") != _sha256_file(comparison):
        raise HighFidelityFaceSecondaryPreviewError("face-secondary comparison package changed")
    if value.get("comparisonOnly") is not True or value.get("physicalAcceptanceAuthority") is not False or value.get("packagePromotionAuthority") is not False or value.get("productionActivation") is not False:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview preparation crossed authority boundary")
    return {**value, "comparisonPackagePath": str(comparison), "preparationPath": str(preparation)}
