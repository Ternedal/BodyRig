from __future__ import annotations

import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Any

from .package import MRBodyError, validate_package
from .sith_body_geometry_authority import (
    SithBodyGeometryAuthorityError,
    read_sith_body_geometry_authority,
)

FORMAT = "bodyrig-source-hair-body-binding"
VERSION = 1
CANDIDATE_FORMAT = "bodyrig-source-hair-candidate"
CANDIDATE_VERSION = 1
SHA256_LENGTH = 64


class SourceHairBodyBindingError(ValueError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != SHA256_LENGTH
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise SourceHairBodyBindingError(f"{label} is invalid")
    return value


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SourceHairBodyBindingError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SourceHairBodyBindingError(f"{label} must be an object")
    return value


def _safe_leaf(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise SourceHairBodyBindingError(f"{label} is invalid")
    name = value.strip()
    if not name or name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
        raise SourceHairBodyBindingError(f"{label} must be a safe leaf filename")
    return name


def _candidate(candidate_dir: str | Path) -> tuple[dict[str, Any], Path, Path, Path, Path]:
    root = Path(candidate_dir).expanduser().resolve()
    receipt_path = root / "source-hair-candidate.json"
    hair_obj = root / "hair_source.obj"
    material = root / "000.mtl"
    receipt = _load_json(receipt_path, label="source hair candidate receipt")
    required = {
        "format", "version", "method", "sourceReconstructionSha256", "sourceMeshSha256",
        "sourceMaterialSha256", "sourceTextureSha256", "donorObjSha256", "hairObjSha256",
        "hairMaterialSha256", "hairTextureSha256", "selectedFaceCount", "selectedVertexCount",
        "seedFaceCount", "bodyHeight", "headSearchRadius", "sourceToDonorDistanceP50",
        "sourceToDonorDistanceP95", "sourceToDonorDistanceMax", "minimumBodyHeightRatio",
        "maximumBodyHeightRatio", "sourceDerived", "generativeGeometry", "bodyTopologyModified",
        "candidateBinding", "comparisonOnly", "humanReviewRequired", "productionReady",
    }
    if set(receipt) != required:
        raise SourceHairBodyBindingError("source hair candidate fields do not match v1")
    if receipt.get("format") != CANDIDATE_FORMAT or receipt.get("version") != CANDIDATE_VERSION:
        raise SourceHairBodyBindingError("source hair candidate format/version mismatch")
    if receipt.get("method") != "retained-sith-connected-head-shell-v1":
        raise SourceHairBodyBindingError("source hair candidate extraction method mismatch")
    if (
        receipt.get("sourceDerived") is not True
        or receipt.get("generativeGeometry") is not False
        or receipt.get("bodyTopologyModified") is not False
        or receipt.get("candidateBinding") != "head-accessory-review-only"
        or receipt.get("comparisonOnly") is not True
        or receipt.get("humanReviewRequired") is not True
        or receipt.get("productionReady") is not False
    ):
        raise SourceHairBodyBindingError("source hair candidate authority boundary is invalid")
    for field in (
        "sourceReconstructionSha256", "sourceMeshSha256", "sourceMaterialSha256", "sourceTextureSha256",
        "donorObjSha256", "hairObjSha256", "hairMaterialSha256", "hairTextureSha256",
    ):
        _sha(receipt.get(field), label=f"source hair candidate {field}")
    for field in ("selectedFaceCount", "selectedVertexCount", "seedFaceCount"):
        value = receipt.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SourceHairBodyBindingError(f"source hair candidate {field} is invalid")

    try:
        mtl_text = material.read_text(encoding="utf-8", errors="strict")
    except (OSError, UnicodeDecodeError) as exc:
        raise SourceHairBodyBindingError("source hair candidate material is unreadable") from exc
    texture_refs = [line.split(maxsplit=1)[1].strip() for line in mtl_text.splitlines() if line.startswith("map_Kd ")]
    if len(texture_refs) != 1:
        raise SourceHairBodyBindingError("source hair candidate material must reference exactly one texture")
    texture_name = _safe_leaf(texture_refs[0], label="source hair candidate texture")
    texture = root / texture_name
    for path, field in (
        (hair_obj, "hairObjSha256"),
        (material, "hairMaterialSha256"),
        (texture, "hairTextureSha256"),
    ):
        if not path.is_file() or _sha256(path) != receipt[field]:
            raise SourceHairBodyBindingError(f"source hair candidate byte hash mismatch: {field}")
    return receipt, receipt_path, hair_obj, material, texture


def build_binding(package_path: str | Path, candidate_dir: str | Path) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    try:
        validated = validate_package(package)
        with zipfile.ZipFile(package, "r") as archive:
            avatar_vrm = archive.read("avatar.vrm")
    except (OSError, zipfile.BadZipFile, KeyError, MRBodyError) as exc:
        raise SourceHairBodyBindingError(f"body package is invalid: {exc}") from exc
    try:
        geometry = read_sith_body_geometry_authority(avatar_vrm)
    except SithBodyGeometryAuthorityError as exc:
        raise SourceHairBodyBindingError(f"body package lacks exact SiTH geometry authority: {exc}") from exc

    candidate, receipt_path, hair_obj, material, texture = _candidate(candidate_dir)
    pairs = {
        "sourceReconstructionSha256": "reconstructionSha256",
        "donorObjSha256": "fittedDonorObjSha256",
        "sourceMeshSha256": "sourceMeshSha256",
        "sourceMaterialSha256": "sourceMaterialSha256",
        "sourceTextureSha256": "sourceTextureSha256",
    }
    for candidate_field, body_field in pairs.items():
        if candidate[candidate_field] != geometry[body_field]:
            raise SourceHairBodyBindingError(
                f"source hair candidate does not match body geometry authority: {candidate_field}"
            )
    texture_name = _safe_leaf(texture.name, label="source hair candidate texture")
    if texture_name != geometry["sourceTextureName"]:
        raise SourceHairBodyBindingError("source hair texture name does not match body geometry authority")

    return {
        "format": FORMAT,
        "version": VERSION,
        "bodyId": str(validated.manifest["id"]),
        "packageSha256": _sha256(package),
        "avatarVrmSha256": _sha256_bytes(avatar_vrm),
        "sourceGeometryAuthority": dict(geometry),
        "hairCandidateReceiptSha256": _sha256(receipt_path),
        "hairObjSha256": _sha256(hair_obj),
        "hairMaterialSha256": _sha256(material),
        "hairTextureSha256": _sha256(texture),
        "bindingStatus": "exact-source-and-donor-match",
        "runtimeIntegrationRequired": True,
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }


def write_binding(package_path: str | Path, candidate_dir: str | Path, output_path: str | Path) -> dict[str, Any]:
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise SourceHairBodyBindingError(f"source hair body binding already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    value = build_binding(package_path, candidate_dir)
    fd, temp_name = tempfile.mkstemp(prefix=f".{output.name}.", suffix=".tmp", dir=output.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)
    return value
