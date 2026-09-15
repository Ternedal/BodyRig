from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .photoreal_identity_calibration import PhotorealIdentityCalibrationError
from .photoreal_identity_calibration_authority import build_identity_calibration_authorized


class PhotorealIdentityCalibrationProvenanceError(PhotorealIdentityCalibrationError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityCalibrationProvenanceError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityCalibrationProvenanceError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealIdentityCalibrationProvenanceError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealIdentityCalibrationProvenanceError(f"{label} is invalid")
    return result


def bind_negative_inventory_provenance(
    calibration: Mapping[str, Any],
    negative_inventory_sha256: str,
) -> dict[str, Any]:
    """Bind an authorized calibration to the verified inventory without changing its v1 digest semantics."""
    calibration_sha256 = _sha(
        calibration.get("identity_calibration_sha256"),
        label="identity calibration SHA-256",
    )
    inventory_sha256 = _sha(
        negative_inventory_sha256,
        label="negative inventory SHA-256",
    )
    binding = {
        "identity_calibration_sha256": calibration_sha256,
        "negative_inventory_sha256": inventory_sha256,
    }
    raw = json.dumps(
        binding,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    result = dict(calibration)
    result["negative_inventory_sha256"] = inventory_sha256
    result["identity_calibration_provenance_sha256"] = hashlib.sha256(raw).hexdigest()
    return result


def build_identity_calibration_provenance_files(
    bank_path: str | Path,
    plan_path: str | Path,
    negative_observations_path: str | Path,
    negative_inventory_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    bank = _read_json(bank_path, label="identity bank")
    plan = _read_json(plan_path, label="identity calibration plan")
    observations = _read_json(negative_observations_path, label="identity negative observations")
    inventory = _read_json(negative_inventory_path, label="identity negative inventory")

    calibration = build_identity_calibration_authorized(bank, plan, observations, inventory)
    inventory_sha256 = _sha(
        plan.get("negative_inventory_sha256"),
        label="identity calibration plan negative inventory SHA-256",
    )
    result = bind_negative_inventory_provenance(calibration, inventory_sha256)

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityCalibrationProvenanceError(
            f"identity calibration output already exists: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise PhotorealIdentityCalibrationProvenanceError(
            f"identity calibration output could not be persisted: {output}"
        ) from exc
    return result
