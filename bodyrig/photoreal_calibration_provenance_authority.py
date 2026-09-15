from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping


class PhotorealCalibrationProvenanceAuthorityError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealCalibrationProvenanceAuthorityError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealCalibrationProvenanceAuthorityError(f"{label} is invalid")
    return result


def require_calibration_provenance(calibration: Mapping[str, Any]) -> tuple[str, str, str]:
    """Require and recompute the #847 negative-inventory provenance seal.

    Returns (identity_calibration_sha256, negative_inventory_sha256,
    identity_calibration_provenance_sha256). Legacy core-only calibrations fail closed.
    """
    calibration_sha = _sha(
        calibration.get("identity_calibration_sha256"),
        label="identity calibration SHA-256",
    )
    inventory_sha = _sha(
        calibration.get("negative_inventory_sha256"),
        label="negative inventory SHA-256",
    )
    provenance_sha = _sha(
        calibration.get("identity_calibration_provenance_sha256"),
        label="identity calibration provenance SHA-256",
    )
    raw = json.dumps(
        {
            "identity_calibration_sha256": calibration_sha,
            "negative_inventory_sha256": inventory_sha,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    expected = hashlib.sha256(raw).hexdigest()
    if provenance_sha != expected:
        raise PhotorealCalibrationProvenanceAuthorityError(
            "identity calibration provenance digest mismatch"
        )
    return calibration_sha, inventory_sha, provenance_sha
