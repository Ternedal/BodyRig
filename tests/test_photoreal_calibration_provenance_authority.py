from __future__ import annotations

import hashlib
import json

import pytest

from bodyrig.photoreal_calibration_provenance_authority import (
    PhotorealCalibrationProvenanceAuthorityError,
    require_calibration_provenance,
)


def _sealed() -> dict[str, object]:
    calibration_sha = "a" * 64
    inventory_sha = "b" * 64
    raw = json.dumps(
        {
            "identity_calibration_sha256": calibration_sha,
            "negative_inventory_sha256": inventory_sha,
        },
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return {
        "identity_calibration_sha256": calibration_sha,
        "negative_inventory_sha256": inventory_sha,
        "identity_calibration_provenance_sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_accepts_exact_sealed_calibration() -> None:
    value = _sealed()
    assert require_calibration_provenance(value) == (
        value["identity_calibration_sha256"],
        value["negative_inventory_sha256"],
        value["identity_calibration_provenance_sha256"],
    )


def test_rejects_legacy_core_only_calibration() -> None:
    with pytest.raises(PhotorealCalibrationProvenanceAuthorityError):
        require_calibration_provenance({"identity_calibration_sha256": "a" * 64})


def test_rejects_tampered_negative_inventory_digest() -> None:
    value = _sealed()
    value["negative_inventory_sha256"] = "c" * 64
    with pytest.raises(PhotorealCalibrationProvenanceAuthorityError, match="digest mismatch"):
        require_calibration_provenance(value)


def test_rejects_tampered_provenance_digest() -> None:
    value = _sealed()
    value["identity_calibration_provenance_sha256"] = "d" * 64
    with pytest.raises(PhotorealCalibrationProvenanceAuthorityError, match="digest mismatch"):
        require_calibration_provenance(value)


@pytest.mark.parametrize("field", [
    "identity_calibration_sha256",
    "negative_inventory_sha256",
    "identity_calibration_provenance_sha256",
])
def test_rejects_non_string_digest_types(field: str) -> None:
    value = _sealed()
    value[field] = 1
    with pytest.raises(PhotorealCalibrationProvenanceAuthorityError):
        require_calibration_provenance(value)
