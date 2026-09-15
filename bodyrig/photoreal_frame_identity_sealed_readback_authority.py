from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .photoreal_frame_identity_authority import (
    PhotorealFrameIdentityAuthorityError,
    authorize_frame_identities,
)
from .photoreal_frame_identity_readback_authority import (
    PhotorealFrameIdentityReadbackAuthorityError,
    validate_identity_matching_readback,
)
from .photoreal_identity_calibration_authority import (
    PhotorealIdentityCalibrationAuthorityError,
    validate_identity_calibration_integrity,
)


class PhotorealFrameIdentitySealedReadbackAuthorityError(PhotorealFrameIdentityReadbackAuthorityError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealFrameIdentitySealedReadbackAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealFrameIdentitySealedReadbackAuthorityError(f"{label} must be a JSON object")
    return value


def _semantic_calibration_view(calibration: Mapping[str, Any]) -> dict[str, Any]:
    """Validate the persisted seal, then expose its canonical core to semantic readback."""
    try:
        validate_identity_calibration_integrity(calibration)
    except PhotorealIdentityCalibrationAuthorityError as exc:
        raise PhotorealFrameIdentitySealedReadbackAuthorityError(str(exc)) from exc

    result = dict(calibration)
    core_sha = result.get("identity_calibration_core_sha256")
    inventory_sha = result.get("negative_inventory_sha256")
    if (core_sha is None) != (inventory_sha is None):
        raise PhotorealFrameIdentitySealedReadbackAuthorityError(
            "identity calibration provenance binding is incomplete"
        )
    if core_sha is not None:
        result["identity_calibration_sha256"] = core_sha
    return result


def validate_sealed_identity_matching_readback(
    bank: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> tuple[int, list[float], float | None, bool]:
    semantic_calibration = _semantic_calibration_view(calibration)
    return validate_identity_matching_readback(bank, semantic_calibration)


def authorize_frame_identity_files_sealed_strict(
    plan_path: str | Path,
    measurements_path: str | Path,
    bank_path: str | Path,
    calibration_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="photoreal dataset plan")
    measurements = _read_json(measurements_path, label="photoreal frame measurements")
    bank = _read_json(bank_path, label="photoreal identity bank")
    calibration = _read_json(calibration_path, label="photoreal identity calibration")

    validate_sealed_identity_matching_readback(bank, calibration)
    try:
        result = authorize_frame_identities(plan, measurements, bank, calibration)
    except PhotorealFrameIdentityAuthorityError:
        raise

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealFrameIdentitySealedReadbackAuthorityError(
            f"frame identity authority output already exists: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
