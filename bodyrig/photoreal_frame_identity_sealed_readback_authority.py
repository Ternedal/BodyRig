from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .photoreal_frame_authorized_observations_integrity import (
    PhotorealAuthorizedObservationsIntegrityError,
    seal_authorized_observations,
)
from .photoreal_frame_identity_authority import (
    PhotorealFrameIdentityAuthorityError,
    authorize_frame_identities,
)
from .photoreal_frame_identity_readback_authority import (
    PhotorealFrameIdentityReadbackAuthorityError,
    validate_identity_matching_readback,
)
from .photoreal_identity_calibration_integrity import (
    PhotorealIdentityCalibrationIntegrityError,
    validate_identity_calibration_integrity,
)
from . import json_io


class PhotorealFrameIdentitySealedReadbackAuthorityError(PhotorealFrameIdentityReadbackAuthorityError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    return json_io.read_json_object(
        source,
        error=PhotorealFrameIdentitySealedReadbackAuthorityError,
        unreadable=f"{label} is unreadable: {source}",
        not_object=f"{label} must be a JSON object",
    )


def validate_sealed_identity_matching_readback(
    bank: Mapping[str, Any],
    calibration: Mapping[str, Any],
) -> tuple[int, list[float], float | None, bool]:
    try:
        validate_identity_calibration_integrity(calibration)
    except PhotorealIdentityCalibrationIntegrityError as exc:
        raise PhotorealFrameIdentitySealedReadbackAuthorityError(str(exc)) from exc
    try:
        return validate_identity_matching_readback(bank, calibration)
    except PhotorealFrameIdentityReadbackAuthorityError as exc:
        raise PhotorealFrameIdentitySealedReadbackAuthorityError(str(exc)) from exc


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
        authorized = authorize_frame_identities(plan, measurements, bank, calibration)
        result = seal_authorized_observations(authorized)
    except PhotorealAuthorizedObservationsIntegrityError as exc:
        raise PhotorealFrameIdentitySealedReadbackAuthorityError(str(exc)) from exc
    except PhotorealFrameIdentityAuthorityError:
        raise

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealFrameIdentitySealedReadbackAuthorityError(
            f"frame identity authority output already exists: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise PhotorealFrameIdentitySealedReadbackAuthorityError(
            f"frame identity authority output could not be persisted: {output}"
        ) from exc
    return result
