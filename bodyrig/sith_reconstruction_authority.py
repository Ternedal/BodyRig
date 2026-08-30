from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

AUTHORITY_FORMAT = "bodyrig-sith-reconstruction-authority"
AUTHORITY_VERSION = 1
AUTHORITY_FILENAME = "reconstruction-authority.json"
SMPLX_FIT_PROFILE = "gender-aware-final-params-canonical-obj-v1"
SMPLX_GENDERS = ("female", "male", "neutral")
SHA256_LENGTH = 64


class SithReconstructionAuthorityError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _stage(workspace: str | Path) -> Path:
    return Path(workspace).expanduser().resolve() / "sith-input-v1"


def _normalize_gender(value: str) -> str:
    gender = str(value).strip().lower()
    if gender not in SMPLX_GENDERS:
        raise SithReconstructionAuthorityError(
            f"SMPL-X gender must be one of: {', '.join(SMPLX_GENDERS)}"
        )
    return gender


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SithReconstructionAuthorityError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SithReconstructionAuthorityError(f"{label} must be an object")
    return value


def _write_create_only(path: Path, value: dict[str, Any]) -> None:
    if path.exists():
        raise SithReconstructionAuthorityError(
            f"SiTH reconstruction authority already exists; refusing overwrite: {path}"
        )
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def write_reconstruction_authority(
    workspace: str | Path,
    *,
    body_model_gender: str,
) -> dict[str, Any]:
    """Create a fail-closed resume receipt for a freshly completed SiTH reconstruction.

    The sidecar deliberately binds the exact reconstruction evidence bytes to the
    gender-aware, final-parameter canonical-SMPL-X generation profile. Older
    workspaces cannot be silently upgraded into this authority contract.
    """

    gender = _normalize_gender(body_model_gender)
    stage = _stage(workspace)
    reconstruction = stage / "reconstruction.json"
    if not reconstruction.is_file():
        raise SithReconstructionAuthorityError(
            "SiTH reconstruction evidence is missing; cannot create resume authority"
        )
    value = {
        "format": AUTHORITY_FORMAT,
        "version": AUTHORITY_VERSION,
        "body_model_gender": gender,
        "smplx_fit_profile": SMPLX_FIT_PROFILE,
        "reconstruction_sha256": _sha256(reconstruction),
    }
    _write_create_only(stage / AUTHORITY_FILENAME, value)
    return value


def validate_reconstruction_authority(
    workspace: str | Path,
    *,
    expected_body_model_gender: str,
) -> dict[str, Any]:
    """Validate that a completed SiTH reconstruction is safe to resume.

    A missing receipt is treated as legacy/incompatible rather than inferred from
    filenames or timestamps. This prevents pre-gender/pre-canonical workspaces
    from crossing into the current SMPL-X -> VRM bridge.
    """

    expected_gender = _normalize_gender(expected_body_model_gender)
    stage = _stage(workspace)
    reconstruction = stage / "reconstruction.json"
    authority_path = stage / AUTHORITY_FILENAME
    if not authority_path.is_file():
        raise SithReconstructionAuthorityError(
            "SiTH reconstruction is legacy/incompatible: reconstruction authority is missing; "
            "rebuild only the SiTH stage with the current gender-aware canonical-SMPL-X pipeline"
        )
    if not reconstruction.is_file():
        raise SithReconstructionAuthorityError("SiTH reconstruction evidence is missing")

    value = _load_json_object(authority_path, label="SiTH reconstruction authority")
    required = {
        "format",
        "version",
        "body_model_gender",
        "smplx_fit_profile",
        "reconstruction_sha256",
    }
    if set(value) != required:
        raise SithReconstructionAuthorityError(
            "SiTH reconstruction authority fields must match v1 exactly"
        )
    if value["format"] != AUTHORITY_FORMAT or value["version"] != AUTHORITY_VERSION:
        raise SithReconstructionAuthorityError(
            "SiTH reconstruction authority format/version mismatch"
        )
    if value["smplx_fit_profile"] != SMPLX_FIT_PROFILE:
        raise SithReconstructionAuthorityError(
            "SiTH reconstruction SMPL-X fit profile is incompatible with the current fitter"
        )
    if value["body_model_gender"] != expected_gender:
        raise SithReconstructionAuthorityError(
            "SiTH reconstruction SMPL-X gender does not match the requested fitter gender"
        )
    expected_hash = value["reconstruction_sha256"]
    if (
        not isinstance(expected_hash, str)
        or len(expected_hash) != SHA256_LENGTH
        or any(ch not in "0123456789abcdef" for ch in expected_hash)
    ):
        raise SithReconstructionAuthorityError(
            "SiTH reconstruction authority SHA-256 is invalid"
        )
    if _sha256(reconstruction) != expected_hash:
        raise SithReconstructionAuthorityError(
            "SiTH reconstruction evidence changed after resume authority was created"
        )
    return value
