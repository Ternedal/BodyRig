from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .avatar import AvatarError, validate_vrm1
from .source_hair_body_binding import SourceHairBodyBindingError, build_binding

FORMAT = "bodyrig-source-hair-review-runtime"
VERSION = 1
BRIDGE_FORMAT = "bodyrig-source-hair-review-bridge"
BRIDGE_VERSION = 1
METADATA_FORMAT = "bodyrig-source-hair-review-runtime-metadata"
METADATA_VERSION = 1
SHA256_LENGTH = 64
REVISION_LENGTH = 40


class SourceHairReviewRuntimeError(ValueError):
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
    if (
        not isinstance(value, str)
        or len(value) != length
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise SourceHairReviewRuntimeError(f"{label} is invalid")
    return value


def _sha(value: Any, *, label: str) -> str:
    return _hex(value, length=SHA256_LENGTH, label=label)


def _revision(value: Any) -> str:
    return _hex(value, length=REVISION_LENGTH, label="BodyRig revision")


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SourceHairReviewRuntimeError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SourceHairReviewRuntimeError(f"{label} must be an object")
    return value


def _write_create_only(path: Path, raw: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise SourceHairReviewRuntimeError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise SourceHairReviewRuntimeError(f"output already exists: {path}") from exc
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _write_json_create_only(path: Path, value: Mapping[str, Any]) -> None:
    raw = (json.dumps(dict(value), indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    _write_create_only(path, raw)


def _extract_avatar(package: Path) -> bytes:
    try:
        with zipfile.ZipFile(package, "r") as archive:
            return archive.read("avatar.vrm")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise SourceHairReviewRuntimeError(f"body package avatar.vrm is unavailable: {exc}") from exc


def prepare(*, package_path: str | Path, candidate_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    candidate = Path(candidate_dir).expanduser().resolve()
    output = Path(output_dir).expanduser().resolve()
    if not package.is_file():
        raise SourceHairReviewRuntimeError(f"body package not found: {package}")
    if not candidate.is_dir():
        raise SourceHairReviewRuntimeError(f"source hair candidate directory not found: {candidate}")
    if not output.is_dir():
        raise SourceHairReviewRuntimeError("hair review staging directory must already exist")

    binding_path = output / "source-hair-body-binding.json"
    avatar_path = output / "base-avatar.vrm"
    prepare_path = output / "source-hair-review-prepare.json"
    if any(path.exists() for path in (binding_path, avatar_path, prepare_path)):
        raise SourceHairReviewRuntimeError("hair review staging output is create-only")
    try:
        binding = build_binding(package, candidate)
    except SourceHairBodyBindingError as exc:
        raise SourceHairReviewRuntimeError(f"source hair/body binding failed: {exc}") from exc
    avatar = _extract_avatar(package)
    avatar_sha = _sha256_bytes(avatar)
    if binding.get("avatarVrmSha256") != avatar_sha:
        raise SourceHairReviewRuntimeError("fresh source hair/body binding does not match extracted avatar bytes")

    _write_create_only(avatar_path, avatar)
    _write_json_create_only(binding_path, binding)
    result = {
        "format": "bodyrig-source-hair-review-prepare",
        "version": 1,
        "bodyId": binding["bodyId"],
        "packageSha256": binding["packageSha256"],
        "baseAvatarVrmSha256": avatar_sha,
        "sourceHairBodyBindingSha256": _sha256(binding_path),
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "hairComponentAuthority": False,
        "productionActivation": False,
    }
    _write_json_create_only(prepare_path, result)
    return result


def _bridge_result(path: Path) -> dict[str, Any]:
    value = _read_json(path, label="source hair review bridge result")
    required = {
        "format", "version", "baseAvatarVrmSha256", "sourceHairBodyBindingSha256",
        "reviewVrmSha256", "targetModelFamily", "skinIndex", "hairMeshIndex",
        "hairVertexCount", "hairFaceCount", "fitMax", "fitRms",
        "nearestDonorDistanceP95", "nearestDonorDistanceMax",
        "bodyprintGeometryReplayApplied", "bodyprintMaxJointDelta",
        "physicalSilhouetteReviewRequired", "comparisonOnly", "humanReviewRequired",
        "hairComponentAuthority", "productionActivation",
    }
    if set(value) != required or value.get("format") != BRIDGE_FORMAT or value.get("version") != BRIDGE_VERSION:
        raise SourceHairReviewRuntimeError("source hair review bridge result fields/format do not match v1")
    for field in ("baseAvatarVrmSha256", "sourceHairBodyBindingSha256", "reviewVrmSha256"):
        _sha(value.get(field), label=f"bridge {field}")
    if value.get("targetModelFamily") not in {"female", "male", "neutral"}:
        raise SourceHairReviewRuntimeError("source hair review target model family is invalid")
    for field in ("skinIndex", "hairMeshIndex", "hairVertexCount", "hairFaceCount"):
        item = value.get(field)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            raise SourceHairReviewRuntimeError(f"source hair review bridge {field} is invalid")
    if value["skinIndex"] != 0 or value["hairVertexCount"] < 3 or value["hairFaceCount"] < 1:
        raise SourceHairReviewRuntimeError("source hair review bridge mesh/skin contract is invalid")
    for field in ("fitMax", "fitRms", "nearestDonorDistanceP95", "nearestDonorDistanceMax", "bodyprintMaxJointDelta"):
        item = value.get(field)
        if isinstance(item, bool) or not isinstance(item, (int, float)) or not 0.0 <= float(item) < float("inf"):
            raise SourceHairReviewRuntimeError(f"source hair review bridge {field} is invalid")
    if not isinstance(value.get("bodyprintGeometryReplayApplied"), bool):
        raise SourceHairReviewRuntimeError("source hair review BodyPrint replay flag is invalid")
    if (
        value.get("physicalSilhouetteReviewRequired") is not True
        or value.get("comparisonOnly") is not True
        or value.get("humanReviewRequired") is not True
        or value.get("hairComponentAuthority") is not False
        or value.get("productionActivation") is not False
    ):
        raise SourceHairReviewRuntimeError("source hair review bridge crossed the review-only authority boundary")
    return value


def _runtime_metadata(document: Mapping[str, Any]) -> dict[str, Any]:
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    value = bodyrig.get("hairReviewRuntime") if isinstance(bodyrig, dict) else None
    required = {
        "format", "version", "baseAvatarVrmSha256", "sourceHairBodyBindingSha256",
        "hairCandidateReceiptSha256", "hairObjSha256", "hairTextureSha256",
        "targetModelFamily", "skinIndex", "bodyprintGeometryReplayApplied",
        "physicalSilhouetteReviewRequired", "comparisonOnly", "humanReviewRequired",
        "productionActivation",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise SourceHairReviewRuntimeError("review VRM runtime metadata fields do not match v1")
    if value.get("format") != METADATA_FORMAT or value.get("version") != METADATA_VERSION:
        raise SourceHairReviewRuntimeError("review VRM runtime metadata format/version mismatch")
    return dict(value)


def finalize(
    *,
    package_path: str | Path,
    candidate_dir: str | Path,
    staging_dir: str | Path,
    bodyrig_revision: str,
    bridge_script_sha256: str,
) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    candidate = Path(candidate_dir).expanduser().resolve()
    staging = Path(staging_dir).expanduser().resolve()
    revision = _revision(bodyrig_revision)
    bridge_script_sha = _sha(bridge_script_sha256, label="hair review bridge script SHA-256")
    if not staging.is_dir():
        raise SourceHairReviewRuntimeError("hair review staging directory is unavailable")

    binding_path = staging / "source-hair-body-binding.json"
    avatar_path = staging / "base-avatar.vrm"
    bridge_result_path = staging / "source-hair-review-bridge.json"
    review_vrm_path = staging / "source-hair-review.vrm"
    receipt_path = staging / "source-hair-review-runtime.json"
    for path in (binding_path, avatar_path, bridge_result_path, review_vrm_path):
        if not path.is_file():
            raise SourceHairReviewRuntimeError(f"hair review staging artifact is missing: {path.name}")
    if receipt_path.exists():
        raise SourceHairReviewRuntimeError("source hair review runtime receipt is create-only")

    persisted_binding = _read_json(binding_path, label="source hair/body binding")
    try:
        fresh_binding = build_binding(package, candidate)
    except SourceHairBodyBindingError as exc:
        raise SourceHairReviewRuntimeError(f"post-build source hair/body revalidation failed: {exc}") from exc
    if persisted_binding != fresh_binding:
        raise SourceHairReviewRuntimeError("source hair/body authority changed during review runtime build")
    binding_sha = _sha256(binding_path)
    avatar_sha = _sha256(avatar_path)
    if fresh_binding.get("avatarVrmSha256") != avatar_sha:
        raise SourceHairReviewRuntimeError("prepared base avatar changed during review runtime build")

    bridge = _bridge_result(bridge_result_path)
    review_vrm = review_vrm_path.read_bytes()
    review_vrm_sha = _sha256_bytes(review_vrm)
    if bridge["baseAvatarVrmSha256"] != avatar_sha:
        raise SourceHairReviewRuntimeError("bridge result targets different base avatar bytes")
    if bridge["sourceHairBodyBindingSha256"] != binding_sha:
        raise SourceHairReviewRuntimeError("bridge result targets different hair/body binding bytes")
    if bridge["reviewVrmSha256"] != review_vrm_sha:
        raise SourceHairReviewRuntimeError("bridge result does not bind exact review VRM bytes")

    try:
        document = validate_vrm1(review_vrm)
    except AvatarError as exc:
        raise SourceHairReviewRuntimeError(f"source hair review artifact is not valid VRM 1.0: {exc}") from exc
    metadata = _runtime_metadata(document)
    expected_metadata = {
        "format": METADATA_FORMAT,
        "version": METADATA_VERSION,
        "baseAvatarVrmSha256": avatar_sha,
        "sourceHairBodyBindingSha256": binding_sha,
        "hairCandidateReceiptSha256": fresh_binding["hairCandidateReceiptSha256"],
        "hairObjSha256": fresh_binding["hairObjSha256"],
        "hairTextureSha256": fresh_binding["hairTextureSha256"],
        "targetModelFamily": fresh_binding["sourceGeometryAuthority"]["bodyModelGender"],
        "skinIndex": 0,
        "bodyprintGeometryReplayApplied": bool(fresh_binding["sourceGeometryAuthority"]["bodyprintGeometryAdjustment"]["applied"]),
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    if metadata != expected_metadata:
        raise SourceHairReviewRuntimeError("review VRM embedded runtime metadata does not match fresh source authority")
    if bridge["targetModelFamily"] != expected_metadata["targetModelFamily"]:
        raise SourceHairReviewRuntimeError("bridge model family differs from fresh source authority")
    if bridge["bodyprintGeometryReplayApplied"] is not expected_metadata["bodyprintGeometryReplayApplied"]:
        raise SourceHairReviewRuntimeError("bridge BodyPrint replay state differs from body authority")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "bodyrigRevision": revision,
        "bridgeScriptSha256": bridge_script_sha,
        "bodyId": fresh_binding["bodyId"],
        "packageSha256": fresh_binding["packageSha256"],
        "baseAvatarVrmSha256": avatar_sha,
        "sourceHairBodyBindingSha256": binding_sha,
        "hairCandidateReceiptSha256": fresh_binding["hairCandidateReceiptSha256"],
        "reviewVrmSha256": review_vrm_sha,
        "bridgeResultSha256": _sha256(bridge_result_path),
        "targetModelFamily": bridge["targetModelFamily"],
        "skinIndex": 0,
        "hairMeshIndex": bridge["hairMeshIndex"],
        "hairVertexCount": bridge["hairVertexCount"],
        "hairFaceCount": bridge["hairFaceCount"],
        "fitMax": bridge["fitMax"],
        "fitRms": bridge["fitRms"],
        "nearestDonorDistanceP95": bridge["nearestDonorDistanceP95"],
        "nearestDonorDistanceMax": bridge["nearestDonorDistanceMax"],
        "bodyprintGeometryReplayApplied": bridge["bodyprintGeometryReplayApplied"],
        "bodyprintMaxJointDelta": bridge["bodyprintMaxJointDelta"],
        "runtimeIntegrationStatus": "review-artifact-ready",
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "hairComponentAuthority": False,
        "productionActivation": False,
    }
    _write_json_create_only(receipt_path, receipt)
    return receipt


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare/finalize exact source-hair review runtime authority.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--package", required=True)
    prepare_parser.add_argument("--candidate-dir", required=True)
    prepare_parser.add_argument("--output-dir", required=True)
    finalize_parser = sub.add_parser("finalize")
    finalize_parser.add_argument("--package", required=True)
    finalize_parser.add_argument("--candidate-dir", required=True)
    finalize_parser.add_argument("--staging-dir", required=True)
    finalize_parser.add_argument("--bodyrig-revision", required=True)
    finalize_parser.add_argument("--bridge-script-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare(package_path=args.package, candidate_dir=args.candidate_dir, output_dir=args.output_dir)
        else:
            result = finalize(
                package_path=args.package,
                candidate_dir=args.candidate_dir,
                staging_dir=args.staging_dir,
                bodyrig_revision=args.bodyrig_revision,
                bridge_script_sha256=args.bridge_script_sha256,
            )
        print(json.dumps(result, separators=(",", ":"), allow_nan=False))
        return 0
    except (SourceHairReviewRuntimeError, OSError) as exc:
        print(f"BodyRig source hair review runtime: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
