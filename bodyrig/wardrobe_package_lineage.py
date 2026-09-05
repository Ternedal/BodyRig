from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path
from typing import Any, Mapping

from .package import MRBodyError, validate_package
from .sith_body_geometry_authority import (
    SithBodyGeometryAuthorityError,
    read_sith_body_geometry_authority,
)

FORMAT = "bodyrig-wardrobe-package-lineage"
VERSION = 1
POLICY_REVISION = "bodyrig-wardrobe-package-lineage-v1"
SHA_FIELDS = (
    "reconstructionSha256",
    "reconstructionAuthoritySha256",
    "fittedDonorObjSha256",
    "fitParamsSha256",
    "sourceMeshSha256",
    "sourceMaterialSha256",
    "sourceTextureSha256",
)


class WardrobePackageLineageError(ValueError):
    pass


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json_sha(value: Mapping[str, Any]) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def inspect_wardrobe_package_lineage(package_path: str | Path) -> dict[str, Any]:
    package = Path(package_path).expanduser().resolve()
    try:
        validated = validate_package(package)
    except MRBodyError as exc:
        raise WardrobePackageLineageError(str(exc)) from exc
    try:
        with zipfile.ZipFile(package, "r") as archive:
            avatar = archive.read("avatar.vrm")
    except (OSError, KeyError, zipfile.BadZipFile) as exc:
        raise WardrobePackageLineageError("could not read validated avatar.vrm for wardrobe lineage") from exc
    try:
        geometry = read_sith_body_geometry_authority(avatar)
    except SithBodyGeometryAuthorityError as exc:
        raise WardrobePackageLineageError(f"wardrobe requires exact SiTH source-geometry authority: {exc}") from exc

    if geometry.get("method") != "exact-sith-reconstruction-bytes-v2":
        raise WardrobePackageLineageError("wardrobe source geometry is not the exact SiTH reconstruction method")
    if geometry.get("exactByteBinding") is not True:
        raise WardrobePackageLineageError("wardrobe source geometry lacks exact byte binding")
    if geometry.get("productionActivation") is not False:
        raise WardrobePackageLineageError("wardrobe source geometry crossed the non-activating source boundary")
    for field in SHA_FIELDS:
        value = str(geometry.get(field) or "")
        if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
            raise WardrobePackageLineageError(f"wardrobe source geometry {field} is not a canonical SHA-256")
    texture_name = str(geometry.get("sourceTextureName") or "").strip()
    if not texture_name or Path(texture_name).name != texture_name or "/" in texture_name or "\\" in texture_name:
        raise WardrobePackageLineageError("wardrobe source texture name is invalid")

    return {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "canonical_body_id": str(validated.manifest["id"]),
        "package_sha256": _sha256_file(package),
        "avatar_sha256": _sha256_bytes(avatar),
        "source_geometry_authority_sha256": _canonical_json_sha(geometry),
        "reconstruction_sha256": str(geometry["reconstructionSha256"]),
        "reconstruction_authority_sha256": str(geometry["reconstructionAuthoritySha256"]),
        "source_mesh_sha256": str(geometry["sourceMeshSha256"]),
        "source_material_sha256": str(geometry["sourceMaterialSha256"]),
        "source_texture_sha256": str(geometry["sourceTextureSha256"]),
        "source_texture_name": texture_name,
        "body_model_gender": str(geometry["bodyModelGender"]),
        "smplx_fit_profile": str(geometry["smplxFitProfile"]),
        "source_outer_surface_used": True,
        "source_grounded": True,
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
    }
