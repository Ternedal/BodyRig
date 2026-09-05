from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .avatar import AvatarError, validate_vrm1
from .bridges.bodyprint_shape_adjust import (
    FIELD_LIMITS,
    GEOMETRY_FIELDS,
    BodyprintAdjustmentError,
    validate_adjustment_payload,
)
from .bridges.sith_pbr_material import PbrMaterialError, _read_glb, _write_glb
from .sith_reconstruction_authority import (
    AUTHORITY_FILENAME,
    SMPLX_FIT_PROFILE,
    SMPLX_GENDERS,
    SithReconstructionAuthorityError,
    validate_reconstruction_authority,
)

FORMAT = "bodyrig-sith-body-geometry-authority"
VERSION = 2
SHA256_LENGTH = 64
BODYPRINT_REPLAY_METHOD = "bodyrig-bodyprint-shape-adjust-v1"


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


def _bodyprint_geometry_adjustment(
    adjustment: Mapping[str, Any] | None,
    *,
    evidence_sha256: str | None,
) -> dict[str, Any]:
    if adjustment is None:
        if evidence_sha256 is not None:
            raise SithBodyGeometryAuthorityError(
                "BodyPrint adjustment evidence SHA is present without an adjustment payload"
            )
        return {
            "method": BODYPRINT_REPLAY_METHOD,
            "applied": False,
            "evidenceSha256": None,
            "changes": [],
        }

    if evidence_sha256 is None:
        raise SithBodyGeometryAuthorityError(
            "BodyPrint adjustment payload is missing its exact evidence SHA"
        )
    evidence_sha = _expected_sha256(
        evidence_sha256,
        field="bodyprint adjustment evidence SHA-256",
    )
    try:
        validated = validate_adjustment_payload(dict(adjustment))
    except BodyprintAdjustmentError as exc:
        raise SithBodyGeometryAuthorityError(
            f"BodyPrint adjustment payload is invalid: {exc}"
        ) from exc

    # Only numeric geometry deltas are embedded. Feedback hashes and free-text
    # reasons stay outside the portable avatar while the exact evidence SHA keeps
    # this replay authority bound to the reviewed source receipt.
    geometry_changes = [
        {"field": str(item["field"]), "delta": float(item["delta"])}
        for item in validated["changes"]
        if item["field"] in GEOMETRY_FIELDS
    ]
    return {
        "method": BODYPRINT_REPLAY_METHOD,
        "applied": bool(geometry_changes),
        "evidenceSha256": evidence_sha,
        "changes": geometry_changes,
    }


def _validate_bodyprint_geometry_adjustment(value: Any) -> dict[str, Any]:
    required = {"method", "applied", "evidenceSha256", "changes"}
    if not isinstance(value, dict) or set(value) != required:
        raise SithBodyGeometryAuthorityError(
            "BodyPrint geometry replay authority fields do not match v1"
        )
    if value.get("method") != BODYPRINT_REPLAY_METHOD:
        raise SithBodyGeometryAuthorityError("BodyPrint geometry replay method is invalid")
    if not isinstance(value.get("applied"), bool):
        raise SithBodyGeometryAuthorityError("BodyPrint geometry replay applied flag is invalid")
    evidence_sha = value.get("evidenceSha256")
    if evidence_sha is not None:
        evidence_sha = _expected_sha256(
            evidence_sha,
            field="bodyprint adjustment evidence SHA-256",
        )
    changes = value.get("changes")
    if not isinstance(changes, list):
        raise SithBodyGeometryAuthorityError("BodyPrint geometry replay changes are invalid")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(changes):
        if not isinstance(item, dict) or set(item) != {"field", "delta"}:
            raise SithBodyGeometryAuthorityError(
                f"BodyPrint geometry replay changes[{index}] fields are invalid"
            )
        field = item.get("field")
        if not isinstance(field, str) or field not in GEOMETRY_FIELDS or field in seen:
            raise SithBodyGeometryAuthorityError(
                f"BodyPrint geometry replay changes[{index}].field is invalid or duplicated"
            )
        seen.add(field)
        delta = item.get("delta")
        if isinstance(delta, bool) or not isinstance(delta, (int, float)):
            raise SithBodyGeometryAuthorityError(
                f"BodyPrint geometry replay changes[{index}].delta is invalid"
            )
        delta = float(delta)
        if (
            not math.isfinite(delta)
            or delta == 0.0
            or abs(delta) > FIELD_LIMITS[field] + 1e-12
        ):
            raise SithBodyGeometryAuthorityError(
                f"BodyPrint geometry replay changes[{index}].delta exceeds the bounded v1 limit"
            )
        normalized.append({"field": field, "delta": delta})
    if bool(normalized) is not value["applied"]:
        raise SithBodyGeometryAuthorityError(
            "BodyPrint geometry replay applied flag does not match its changes"
        )
    if evidence_sha is None and normalized:
        raise SithBodyGeometryAuthorityError(
            "BodyPrint geometry replay changes are missing exact adjustment evidence authority"
        )
    return {
        "method": BODYPRINT_REPLAY_METHOD,
        "applied": bool(normalized),
        "evidenceSha256": evidence_sha,
        "changes": normalized,
    }


def _source_authority(
    workspace: str | Path,
    *,
    bodyprint_adjustment: Mapping[str, Any] | None = None,
    bodyprint_adjustment_evidence_sha256: str | None = None,
) -> dict[str, Any]:
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

    reconstruction_authority_path = stage / AUTHORITY_FILENAME
    if not reconstruction_authority_path.is_file():
        raise SithBodyGeometryAuthorityError("SiTH reconstruction model-family authority is missing")
    raw_reconstruction_authority = _load_json(
        reconstruction_authority_path,
        label="SiTH reconstruction model-family authority",
    )
    body_model_gender = raw_reconstruction_authority.get("body_model_gender")
    if body_model_gender not in SMPLX_GENDERS:
        raise SithBodyGeometryAuthorityError("SiTH reconstruction body-model gender is invalid")
    try:
        reconstruction_authority = validate_reconstruction_authority(
            root,
            expected_body_model_gender=body_model_gender,
        )
    except SithReconstructionAuthorityError as exc:
        raise SithBodyGeometryAuthorityError(
            f"SiTH reconstruction model-family authority is invalid: {exc}"
        ) from exc
    if reconstruction_authority.get("smplx_fit_profile") != SMPLX_FIT_PROFILE:
        raise SithBodyGeometryAuthorityError("SiTH reconstruction SMPL-X fit profile is invalid")
    if reconstruction_authority.get("reconstruction_sha256") != _sha256(reconstruction_path):
        raise SithBodyGeometryAuthorityError(
            "SiTH reconstruction model-family authority is bound to different reconstruction bytes"
        )

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
        "method": "exact-sith-reconstruction-bytes-v2",
        "reconstructionSha256": _sha256(reconstruction_path),
        "reconstructionAuthoritySha256": _sha256(reconstruction_authority_path),
        "bodyModelGender": body_model_gender,
        "smplxFitProfile": SMPLX_FIT_PROFILE,
        **{field: expected for field, (_path, expected) in files.items()},
        "sourceTextureName": texture_name,
        "bodyprintGeometryAdjustment": _bodyprint_geometry_adjustment(
            bodyprint_adjustment,
            evidence_sha256=bodyprint_adjustment_evidence_sha256,
        ),
        "exactByteBinding": True,
        "hairCandidateBindingEligible": True,
        "productionActivation": False,
    }


def bind_sith_body_geometry_authority(
    avatar_vrm: bytes,
    workspace: str | Path,
    *,
    bodyprint_adjustment: Mapping[str, Any] | None = None,
    bodyprint_adjustment_evidence_sha256: str | None = None,
) -> bytes:
    """Bind exact donor/source/model-family/shape-replay authority into a SiTH body VRM.

    Hair/eye component candidates can later prove that they were derived from the
    exact reconstruction/donor bytes that produced this body revision and replay
    the same bounded BodyPrint rest-pose geometry adjustment. This metadata is
    evidence only and never grants component or production authority.
    """

    authority = _source_authority(
        workspace,
        bodyprint_adjustment=bodyprint_adjustment,
        bodyprint_adjustment_evidence_sha256=bodyprint_adjustment_evidence_sha256,
    )
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
        "format", "version", "method", "reconstructionSha256", "reconstructionAuthoritySha256",
        "bodyModelGender", "smplxFitProfile", "fittedDonorObjSha256", "fitParamsSha256",
        "sourceMeshSha256", "sourceMaterialSha256", "sourceTextureSha256", "sourceTextureName",
        "bodyprintGeometryAdjustment", "exactByteBinding", "hairCandidateBindingEligible",
        "productionActivation",
    }
    if set(authority) != required or authority.get("format") != FORMAT or authority.get("version") != VERSION:
        raise SithBodyGeometryAuthorityError("SiTH source geometry authority fields do not match v2")
    for field in (
        "reconstructionSha256", "reconstructionAuthoritySha256", "fittedDonorObjSha256", "fitParamsSha256",
        "sourceMeshSha256", "sourceMaterialSha256", "sourceTextureSha256",
    ):
        _expected_sha256(authority.get(field), field=field)
    _safe_leaf(authority.get("sourceTextureName"), label="SiTH source texture")
    if authority.get("bodyModelGender") not in SMPLX_GENDERS:
        raise SithBodyGeometryAuthorityError("SiTH source geometry body-model gender is invalid")
    if authority.get("smplxFitProfile") != SMPLX_FIT_PROFILE:
        raise SithBodyGeometryAuthorityError("SiTH source geometry fit profile is invalid")
    replay = _validate_bodyprint_geometry_adjustment(authority.get("bodyprintGeometryAdjustment"))
    if replay != authority["bodyprintGeometryAdjustment"]:
        raise SithBodyGeometryAuthorityError("BodyPrint geometry replay authority is not canonical")
    if (
        authority.get("method") != "exact-sith-reconstruction-bytes-v2"
        or authority.get("exactByteBinding") is not True
        or authority.get("hairCandidateBindingEligible") is not True
        or authority.get("productionActivation") is not False
    ):
        raise SithBodyGeometryAuthorityError("SiTH source geometry authority boundary is invalid")
    return authority
