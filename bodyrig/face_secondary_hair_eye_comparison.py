from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from .face_secondary_hair_eye_review import (
    FaceSecondaryHairEyeReviewError,
    read_runtime,
)
from .high_fidelity_face_secondary_preview import _write_package
from .package import MRBodyError, validate_package

FORMAT = "bodyrig-face-secondary-hair-eye-comparison"
VERSION = 1
PACKAGE_NAME = "face-secondary-hair-eye-comparison.mrbody"
RECEIPT_NAME = "face-secondary-hair-eye-comparison.json"


class FaceSecondaryHairEyeComparisonError(RuntimeError):
    pass


def _is_v1(value: Any) -> bool:
    return not isinstance(value, bool) and value == VERSION


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise FaceSecondaryHairEyeComparisonError(f"{label} is missing or symlinked")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FaceSecondaryHairEyeComparisonError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise FaceSecondaryHairEyeComparisonError(f"{label} must be an object")
    return value


def build(package_path: str | Path, runtime_dir: str | Path, output_dir: str | Path, *, bodyrig_revision: str) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    runtime_root = Path(runtime_dir).expanduser().resolve()
    root = Path(output_dir).expanduser().resolve()
    revision = str(bodyrig_revision or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise FaceSecondaryHairEyeComparisonError("BodyRig revision is not canonical")
    if root.exists():
        raise FaceSecondaryHairEyeComparisonError("face-secondary hair+eye comparison output is create-only")
    if not package.is_file() or package.is_symlink():
        raise FaceSecondaryHairEyeComparisonError("source package is missing or symlinked")
    try:
        validated = validate_package(package)
        runtime = read_runtime(runtime_root)
    except (MRBodyError, FaceSecondaryHairEyeReviewError) as exc:
        raise FaceSecondaryHairEyeComparisonError(str(exc)) from exc
    package_sha = _sha256(package)
    body_id = str(validated.manifest["id"])
    if runtime.get("bodyrigRevision") != revision:
        raise FaceSecondaryHairEyeComparisonError("face-secondary hair+eye runtime belongs to a different BodyRig revision")
    if runtime.get("sourcePackageSha256") != package_sha or runtime.get("canonicalBodyId") != body_id:
        raise FaceSecondaryHairEyeComparisonError("face-secondary hair+eye runtime targets different package/body authority")
    vrm_path = Path(runtime["reviewVrmPath"]).resolve()
    receipt_path = Path(runtime["receiptPath"]).resolve()
    review_vrm = vrm_path.read_bytes()

    root.mkdir(parents=True)
    comparison = root / PACKAGE_NAME
    receipt_path_out = root / RECEIPT_NAME
    try:
        _write_package(package, comparison, avatar_vrm=review_vrm)
        comparison_validated = validate_package(comparison)
        if str(comparison_validated.manifest["id"]) != body_id:
            raise FaceSecondaryHairEyeComparisonError("comparison package changed canonical body identity")
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "bodyrigRevision": revision,
            "canonicalBodyId": body_id,
            "sourcePackageSha256": package_sha,
            "sourceRuntimeReceiptSha256": _sha256(receipt_path),
            "sourceReviewVrmSha256": _sha256(vrm_path),
            "comparisonPackageSha256": _sha256(comparison),
            "comparisonPackageName": PACKAGE_NAME,
            "comparisonOnly": True,
            "physicalAcceptanceAuthority": False,
            "humanReviewRequired": True,
            "packagePromotionAuthority": False,
            "productionActivation": False,
        }
        raw = json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n"
        fd = os.open(receipt_path_out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        comparison.unlink(missing_ok=True)
        receipt_path_out.unlink(missing_ok=True)
        try:
            root.rmdir()
        except OSError:
            pass
        raise
    return {**receipt, "comparisonPackagePath": str(comparison), "receiptPath": str(receipt_path_out)}


def read(output_dir: str | Path) -> dict[str, Any]:
    root = Path(output_dir).expanduser().resolve()
    package = root / PACKAGE_NAME
    receipt_path = root / RECEIPT_NAME
    value = _read_json(receipt_path, label="face-secondary hair+eye comparison receipt")
    if value.get("format") != FORMAT or not _is_v1(value.get("version")):
        raise FaceSecondaryHairEyeComparisonError("face-secondary hair+eye comparison format/version mismatch")
    if value.get("comparisonPackageName") != PACKAGE_NAME or value.get("comparisonPackageSha256") != _sha256(package):
        raise FaceSecondaryHairEyeComparisonError("face-secondary hair+eye comparison package bytes changed")
    if (
        value.get("comparisonOnly") is not True
        or value.get("physicalAcceptanceAuthority") is not False
        or value.get("humanReviewRequired") is not True
        or value.get("packagePromotionAuthority") is not False
        or value.get("productionActivation") is not False
    ):
        raise FaceSecondaryHairEyeComparisonError("face-secondary hair+eye comparison crossed authority boundary")
    try:
        validated = validate_package(package)
    except MRBodyError as exc:
        raise FaceSecondaryHairEyeComparisonError(str(exc)) from exc
    if str(validated.manifest["id"]) != value.get("canonicalBodyId"):
        raise FaceSecondaryHairEyeComparisonError("comparison package body identity changed")
    return {**value, "comparisonPackagePath": str(package), "receiptPath": str(receipt_path)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Materialize/verify a comparison-only package carrying the face-secondary-on-hair-eye review VRM.")
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--package", required=True)
    build_parser.add_argument("--runtime-dir", required=True)
    build_parser.add_argument("--output-dir", required=True)
    build_parser.add_argument("--bodyrig-revision", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.package, args.runtime_dir, args.output_dir, bodyrig_revision=args.bodyrig_revision)
        else:
            result = read(args.output_dir)
        print(json.dumps(result, separators=(",", ":"), allow_nan=False))
        return 0
    except (FaceSecondaryHairEyeComparisonError, FaceSecondaryHairEyeReviewError, MRBodyError, OSError) as exc:
        print(f"BodyRig face-secondary hair+eye comparison: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
