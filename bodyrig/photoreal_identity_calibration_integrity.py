from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from .photoreal_identity_calibration import (
    PhotorealIdentityCalibrationError,
    _canonical_calibration_digest,
)


class PhotorealIdentityCalibrationIntegrityError(PhotorealIdentityCalibrationError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealIdentityCalibrationIntegrityError(f"{label} must be a JSON string")
    result = value.strip().lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealIdentityCalibrationIntegrityError(f"{label} is invalid")
    return result


def calibration_provenance_sha256(
    identity_calibration_sha256: str,
    negative_inventory_sha256: str,
) -> str:
    binding = {
        "identity_calibration_sha256": _sha(
            identity_calibration_sha256,
            label="identity calibration SHA-256",
        ),
        "negative_inventory_sha256": _sha(
            negative_inventory_sha256,
            label="negative inventory SHA-256",
        ),
    }
    raw = json.dumps(
        binding,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def validate_identity_calibration_integrity(calibration: Mapping[str, Any]) -> str:
    """Recompute the canonical calibration core and optional inventory provenance seal."""
    if not isinstance(calibration, Mapping):
        raise PhotorealIdentityCalibrationIntegrityError(
            "identity calibration must be a JSON object"
        )

    declared_core = _sha(
        calibration.get("identity_calibration_sha256"),
        label="identity calibration SHA-256",
    )
    try:
        observed_core = _canonical_calibration_digest(calibration)
    except (TypeError, ValueError) as exc:
        raise PhotorealIdentityCalibrationIntegrityError(
            "identity calibration core is not canonical JSON"
        ) from exc
    if declared_core != observed_core:
        raise PhotorealIdentityCalibrationIntegrityError(
            "identity calibration core canonical digest mismatch"
        )

    has_inventory = "negative_inventory_sha256" in calibration
    has_provenance = "identity_calibration_provenance_sha256" in calibration
    if has_inventory != has_provenance:
        raise PhotorealIdentityCalibrationIntegrityError(
            "identity calibration provenance binding is incomplete"
        )
    if not has_inventory:
        return declared_core

    inventory_sha256 = _sha(
        calibration.get("negative_inventory_sha256"),
        label="negative inventory SHA-256",
    )
    declared_provenance = _sha(
        calibration.get("identity_calibration_provenance_sha256"),
        label="identity calibration provenance SHA-256",
    )
    observed_provenance = calibration_provenance_sha256(
        declared_core,
        inventory_sha256,
    )
    if declared_provenance != observed_provenance:
        raise PhotorealIdentityCalibrationIntegrityError(
            "identity calibration provenance digest mismatch"
        )
    return declared_core
