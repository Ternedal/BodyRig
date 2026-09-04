from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .avatar import AvatarError, validate_vrm1
from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb

FORMAT = "bodyrig-sith-body-geometry-authority"
VERSION = 1
SHA256_LENGTH = 64


class SithBodyGeometryAuthorityError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SithBodyGeometryAuthorityError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SithBodyGeometryAuthorityError(f"{label} must be an object")
    return value


def _expected_sha256(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != SHA256_LENGTH
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise SithBodyGeometryAuthorityError(f"SiTH reconstruction {field} is invalid")
    return value


def _safe_leaf(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise SithBodyGeometryAuthorityError(f"{label} is invalid")
    name = value.strip()
    if not name or name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
        raise SithBodyGeometryAuthorityError(f"{label} must be a safe leaf filename")
    return name


def _source_authority(workspace: str | Path) -> dict[str, Any]:
    root = Path(workspace).expanduser().resolve()
    stage = root / "sith-input-v1"
    reconstruction_path = stage / "reconstruction.json"
    if not reconstruction_path.is_file():
        raise SithBodyGeometryAuthorityError("SiTH reconstruction evidence is missing")
    reconstruction = _load_json(reconstruction_path, label="SiTH reconstruction evidence")
    if reconstruction.get("format") != "bodyrig-sith-reconstruction" or reconstruction.get("version") != 1:
        raise SithBodyGeometryAuthorityError("SiTH reconstruction format/version mismatch")
    details = reconstruction.get("reconstruction")
    if not isinstance(details, dict) or details.get("grid_size") != 300 or details.get("save_uv") is not True:
        raise SithBodyGeometryAuthorityError("SiTH reconstruction is not the pinned UV profile")

    texture_name = _safe_leaf(details.get("mesh_texture_name"), label="SiTH source texture")
    files = {
        "fittedDonorObjSha256": (
            stage / "smplx" / "000_smplx.obj",
            _expected_sha256(details.get("smplx_obj_sha256"), field="smplx_obj_sha256"),
        ),
        "fitParamsSha256": (
            stage / "smplx" / "000_fit.json",
            _expected_sha256(details.get("fit_params_sha256"), field="fit_params_sha256"),
        ),
        "sourceMeshSha256": (
            stage / "meshes" / "000_reco.obj",
            _expected_sha256(details.get("mesh_obj_sha256"), field="mesh_obj_sha256"),
        ),
        "sourceMaterialSha256": (
            stage / "meshes" / "000.mtl",
            _expected_sha256(details.get("mesh_mtl_sha256"), field="mesh_mtl_sha256"),
        ),
        "sourceTextureSha256": (
            stage / "meshes" / texture_name,
            _expected_sha256(details.get("mesh_texture_sha256"), field="mesh_texture_sha256"),
        ),
    }
    for field, (path, expected) in files.items():
        if not path.is_file():
            raise SithBodyGeometryAuthorityError(f"SiTH geometry authority artifact is missing: {path.name}")
        if _sha256(path) != expected:
            raise SithBodyGeometryAuthorityError(f"SiTH geometry authority byte hash mismatch: {field}")

    return {
        "format": FORMAT,
        "version": VERSION,
        "method": "exact-sith-reconstruction-bytes-v1",
        "reconstructionSha256": _sha256(reconstruction_path),
        **{field: expected for field, (_path, expected) in files.items()},
        "sourceTextureName": texture_name,
        "exactByteBinding": True,
        "hairCandidateBindingEligible": True,
        "productionActivation": False,
    }


def bind_sith_body_geometry_authority(avatar_vrm: bytes, workspace: str | Path) -> bytes:
    """Bind exact donor/source bytes into the canonical built-in SiTH body VRM.

    Hair/eye component candidates can later prove that they were derived from the
    exact reconstruction/donor bytes that produced this body revision. This
    metadata is evidence only and never grants component or production authority.
    """

    authority = _source_authority(workspace)
    try:
        document, binary = _read_glb(avatar_vrm)
    except PbrMaterialError as exc:
        raise SithBodyGeometryAuthorityError(str(exc)) from exc

    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise SithBodyGeometryAuthorityError("BodyRig VRM metadata is missing")
    geometry = bodyrig.get("geometryAuthority")
    if not isinstance(geometry, dict):
        raise SithBodyGeometryAuthorityError("SMPL-X donor geometry authority is missing")
    if (
        geometry.get("method") != "smplx-fitted-donor-topology-v1"
        or geometry.get("sourceMeshGeometryUsed") is not False
        or geometry.get("stableTopology") is not True
    ):
        raise SithBodyGeometryAuthorityError("SMPL-X donor geometry authority is incompatible")
    if "sourceGeometryAuthority" in bodyrig:
        raise SithBodyGeometryAuthorityError("SiTH source geometry authority is already bound")

    bodyrig["sourceGeometryAuthority"] = authority
    result = _write_glb(document, binary)
    try:
        validate_vrm1(result)
    except AvatarError as exc:
        raise SithBodyGeometryAuthorityError(f"geometry-bound avatar is no longer valid VRM 1.0: {exc}") from exc
    return result


def read_sith_body_geometry_authority(avatar_vrm: bytes) -> dict[str, Any]:
    try:
        document, _binary = _read_glb(avatar_vrm)
    except PbrMaterialError as exc:
        raise SithBodyGeometryAuthorityError(str(exc)) from exc
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    authority = bodyrig.get("sourceGeometryAuthority") if isinstance(bodyrig, dict) else None
    if not isinstance(authority, dict):
        raise SithBodyGeometryAuthorityError("SiTH source geometry authority is missing")
    required = {
        "format", "version", "method", "reconstructionSha256", "fittedDonorObjSha256",
        "fitParamsSha256", "sourceMeshSha256", "sourceMaterialSha256", "sourceTextureSha256",
        "sourceTextureName", "exactByteBinding", "hairCandidateBindingEligible", "productionActivation",
    }
    if set(authority) != required or authority.get("format") != FORMAT or authority.get("version") != VERSION:
        raise SithBodyGeometryAuthorityError("SiTH source geometry authority fields do not match v1")
    for field in (
        "reconstructionSha256", "fittedDonorObjSha256", "fitParamsSha256",
        "sourceMeshSha256", "sourceMaterialSha256", "sourceTextureSha256",
    ):
        _expected_sha256(authority.get(field), field=field)
    _safe_leaf(authority.get("sourceTextureName"), label="SiTH source texture")
    if (
        authority.get("method") != "exact-sith-reconstruction-bytes-v1"
        or authority.get("exactByteBinding") is not True
        or authority.get("hairCandidateBindingEligible") is not True
        or authority.get("productionActivation") is not False
    ):
        raise SithBodyGeometryAuthorityError("SiTH source geometry authority boundary is invalid")
    return authority
