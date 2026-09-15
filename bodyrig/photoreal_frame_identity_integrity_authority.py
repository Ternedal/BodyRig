from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .photoreal_frame_identity_authority import (
    PhotorealFrameIdentityAuthorityError,
    authorize_frame_identities,
)
from .photoreal_identity_calibration_integrity import (
    PhotorealIdentityCalibrationIntegrityError,
    validate_identity_calibration_integrity,
)


class PhotorealFrameIdentityIntegrityAuthorityError(PhotorealFrameIdentityAuthorityError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealFrameIdentityIntegrityAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealFrameIdentityIntegrityAuthorityError(f"{label} must be a JSON object")
    return value


def authorize_frame_identity_files_integrity_checked(
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
    try:
        validate_identity_calibration_integrity(calibration)
    except PhotorealIdentityCalibrationIntegrityError as exc:
        raise PhotorealFrameIdentityIntegrityAuthorityError(str(exc)) from exc

    result = authorize_frame_identities(plan, measurements, bank, calibration)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealFrameIdentityIntegrityAuthorityError(
            f"frame identity authority output already exists: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise PhotorealFrameIdentityIntegrityAuthorityError(
            f"frame identity authority output could not be persisted: {output}"
        ) from exc
    return result
