from __future__ import annotations

import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .high_fidelity_face_secondary_runtime import (
    HighFidelityFaceSecondaryRuntimeError,
    read_runtime,
)
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-high-fidelity-face-secondary-preview-preparation"
VERSION = 1
PREVIEW_FORMAT = "bodyrig-high-fidelity-face-secondary-preview-authority"
PREVIEW_VERSION = 1
COMPARISON_PACKAGE_NAME = "face-secondary-review-comparison.mrbody"
PREPARATION_NAME = "face-secondary-preview-preparation.json"
PREVIEW_NAME = "face-secondary-preview-authority.json"
CANONICAL_VIEWS = ("front-full", "three-quarter-full", "side-full", "face-front")
DIAGNOSTIC_VIEWS = ("face-zoom", "eyes-closeup", "mouth-open")


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


def _sha(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise HighFidelityFaceSecondaryPreviewError(f"{label} is not a canonical SHA-256")
    return clean


def _revision(value: Any, *, label: str = "BodyRig revision") -> str:
    clean = str(value or "").strip().lower()
    if len(clean) != 40 or any(ch not in "0123456789abcdef" for ch in clean):
        raise HighFidelityFaceSecondaryPreviewError(f"{label} is not a canonical Git SHA")
    return clean


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityFaceSecondaryPreviewError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise HighFidelityFaceSecondaryPreviewError(f"{label} must be a JSON object")
    return value


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
    bodyrig_revision = _revision(bodyrig_revision)
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
    value = _read_json(preparation, label="face-secondary preview preparation")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview preparation format/version mismatch")
    _revision(value.get("bodyrigRevision"))
    for field in ("sourcePackageSha256", "sourceRuntimeReceiptSha256", "sourceReviewVrmSha256", "comparisonPackageSha256"):
        _sha(value.get(field), label=field)
    if value.get("comparisonPackageName") != COMPARISON_PACKAGE_NAME or value.get("comparisonPackageSha256") != _sha256_file(comparison):
        raise HighFidelityFaceSecondaryPreviewError("face-secondary comparison package changed")
    if value.get("comparisonOnly") is not True or value.get("physicalAcceptanceAuthority") is not False or value.get("humanReviewRequired") is not True or value.get("packagePromotionAuthority") is not False or value.get("productionActivation") is not False:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview preparation crossed authority boundary")
    return {**value, "comparisonPackagePath": str(comparison), "preparationPath": str(preparation)}


def _render_evidence(preparation_dir: Path, runtime_dir: Path, render_dir: Path) -> dict[str, Any]:
    prep = read_preparation(preparation_dir)
    try:
        runtime = read_runtime(runtime_dir)
    except HighFidelityFaceSecondaryRuntimeError as exc:
        raise HighFidelityFaceSecondaryPreviewError(str(exc)) from exc
    receipt_path = Path(runtime["receiptPath"]).resolve()
    vrm_path = Path(runtime["reviewVrmPath"]).resolve()
    if prep["sourceRuntimeReceiptSha256"] != _sha256_file(receipt_path) or prep["sourceReviewVrmSha256"] != _sha256_file(vrm_path):
        raise HighFidelityFaceSecondaryPreviewError("face-secondary runtime bytes changed after preview preparation")
    if runtime.get("sourcePackageSha256") != prep["sourcePackageSha256"] or runtime.get("canonicalBodyId") != prep["canonicalBodyId"] or runtime.get("bodyrigRevision") != prep["bodyrigRevision"]:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary runtime no longer matches preview preparation")

    comparison_authority_path = render_dir / "comparison-authority.json"
    manifest_path = render_dir / "snapshots" / "fidelity-render-set.json"
    if not comparison_authority_path.is_file() or not manifest_path.is_file():
        raise HighFidelityFaceSecondaryPreviewError("face-secondary Windows render evidence is incomplete")
    comparison = _read_json(comparison_authority_path, label="face-secondary renderer comparison authority")
    if comparison.get("format") != "bodyrig-fidelity-comparison-authority" or comparison.get("version") != 1 or comparison.get("authority") != "validated-package-comparison-only":
        raise HighFidelityFaceSecondaryPreviewError("renderer comparison authority is not canonical package-comparison evidence")
    if comparison.get("bodyrig_revision") != prep["bodyrigRevision"] or comparison.get("package_sha256") != prep["comparisonPackageSha256"]:
        raise HighFidelityFaceSecondaryPreviewError("renderer comparison authority targets different revision/package bytes")
    if comparison.get("physical_acceptance_authority") is not False or comparison.get("comparison_only") is not True or comparison.get("production_activation") is not False:
        raise HighFidelityFaceSecondaryPreviewError("renderer comparison authority crossed the review-only boundary")

    manifest = _read_json(manifest_path, label="face-secondary renderer snapshot manifest")
    if manifest.get("format") != "bodyrig-fidelity-render-set" or manifest.get("version") != 1 or manifest.get("semantics") != "visual-fidelity-not-identity-verification":
        raise HighFidelityFaceSecondaryPreviewError("renderer snapshot manifest format/semantics mismatch")
    if manifest.get("body_id") != prep["canonicalBodyId"] or manifest.get("package_sha256") != prep["comparisonPackageSha256"]:
        raise HighFidelityFaceSecondaryPreviewError("renderer snapshot manifest targets different body/package bytes")
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or [item.get("view") for item in snapshots if isinstance(item, dict)] != list(CANONICAL_VIEWS):
        raise HighFidelityFaceSecondaryPreviewError("renderer canonical snapshot sequence is not v1")
    canonical: dict[str, str] = {}
    for item in snapshots:
        if not isinstance(item, dict) or item.get("file") != f"{item.get('view')}.png" or item.get("width") != 1024 or item.get("height") != 1024:
            raise HighFidelityFaceSecondaryPreviewError("renderer canonical snapshot metadata is invalid")
        path = render_dir / "snapshots" / str(item["file"])
        if not path.is_file():
            raise HighFidelityFaceSecondaryPreviewError(f"renderer canonical snapshot is missing: {item.get('view')}")
        actual = _sha256_file(path)
        if _sha(item.get("sha256"), label=f"{item.get('view')} SHA-256") != actual:
            raise HighFidelityFaceSecondaryPreviewError(f"renderer canonical snapshot changed: {item.get('view')}")
        canonical[str(item["view"])] = actual

    diagnostics: dict[str, str] = {}
    for view in DIAGNOSTIC_VIEWS:
        path = render_dir / "snapshots" / f"{view}.png"
        if not path.is_file():
            raise HighFidelityFaceSecondaryPreviewError(f"required face-secondary diagnostic view is missing: {view}")
        diagnostics[view] = _sha256_file(path)

    return {
        "format": PREVIEW_FORMAT,
        "version": PREVIEW_VERSION,
        "bodyrigRevision": prep["bodyrigRevision"],
        "canonicalBodyId": prep["canonicalBodyId"],
        "sourcePackageSha256": prep["sourcePackageSha256"],
        "sourceRuntimeReceiptSha256": prep["sourceRuntimeReceiptSha256"],
        "sourceReviewVrmSha256": prep["sourceReviewVrmSha256"],
        "comparisonPackageSha256": prep["comparisonPackageSha256"],
        "comparisonAuthoritySha256": _sha256_file(comparison_authority_path),
        "renderManifestSha256": _sha256_file(manifest_path),
        "canonicalViewSha256": canonical,
        "diagnosticViewSha256": diagnostics,
        "requiredHumanReview": ["eyebrow_appearance", "lip_boundary", "mouth_interior", "teeth", "eyelashes"],
        "mouthOpenPoseRendered": True,
        "comparisonOnly": True,
        "physicalAcceptanceAuthority": False,
        "humanReviewRequired": True,
        "faceSecondaryComponentAuthority": False,
        "packagePromotionAuthority": False,
        "productionActivation": False,
    }


def finalize_preview(preparation_dir: str | Path, runtime_dir: str | Path, render_dir: str | Path) -> dict[str, Any]:
    prep_root = Path(preparation_dir).expanduser().resolve()
    evidence = _render_evidence(prep_root, Path(runtime_dir).expanduser().resolve(), Path(render_dir).expanduser().resolve())
    path = prep_root / PREVIEW_NAME
    if path.exists():
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview authority is create-only")
    receipt = {
        **evidence,
        "finalizedUtc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
    }
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview authority is create-only") from exc
    return {**receipt, "previewAuthorityPath": str(path)}


def read_preview(preparation_dir: str | Path, runtime_dir: str | Path, render_dir: str | Path) -> dict[str, Any]:
    prep_root = Path(preparation_dir).expanduser().resolve()
    path = prep_root / PREVIEW_NAME
    if not path.is_file():
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview authority is missing")
    value = _read_json(path, label="face-secondary preview authority")
    expected = _render_evidence(prep_root, Path(runtime_dir).expanduser().resolve(), Path(render_dir).expanduser().resolve())
    if set(value) != set(expected) | {"finalizedUtc"}:
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview authority fields are not canonical")
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise HighFidelityFaceSecondaryPreviewError(f"face-secondary preview authority is stale: {field}")
    if not str(value.get("finalizedUtc") or "").strip():
        raise HighFidelityFaceSecondaryPreviewError("face-secondary preview authority lacks finalization time")
    return {**value, "previewAuthorityPath": str(path)}
