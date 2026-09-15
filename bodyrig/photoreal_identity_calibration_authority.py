from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .photoreal_identity_calibration import (
    PhotorealIdentityCalibrationError,
    build_identity_calibration,
)
from .photoreal_identity_negative_verify import (
    INVENTORY_FORMAT,
    INVENTORY_VERSION,
    LABEL_AUTHORITY,
    PhotorealIdentityNegativeVerifyError,
    canonical_identity_negative_inventory_sha256,
)

PLAN_FORMAT = "bodyrig-photoreal-identity-calibration-plan"
PLAN_VERSION = 1


class PhotorealIdentityCalibrationAuthorityError(PhotorealIdentityCalibrationError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealIdentityCalibrationAuthorityError(f"{label} is invalid")
    return result


def validate_negative_inventory_binding(
    negative_inventory: Mapping[str, Any],
    plan: Mapping[str, Any],
    bank: Mapping[str, Any],
) -> str:
    version = negative_inventory.get("version")
    if (
        negative_inventory.get("format") != INVENTORY_FORMAT
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version != INVENTORY_VERSION
    ):
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory format/version mismatch")
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise PhotorealIdentityCalibrationAuthorityError("identity calibration plan format/version mismatch")
    if negative_inventory.get("label_authority") != LABEL_AUTHORITY:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory label authority mismatch")
    if negative_inventory.get("calibration_only") is not True or negative_inventory.get("photoreal_teacher_input") is not False:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory crossed calibration/teacher boundary")
    if negative_inventory.get("teacher_training_authorized") is not False:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory crossed training authority")
    if negative_inventory.get("identity_matching_authorized") is not False:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory crossed matching authority")
    if negative_inventory.get("build_only") is not True or negative_inventory.get("runtime_dependency") is not False:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory build/runtime authority is invalid")
    if negative_inventory.get("production_activation") is not False:
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory crossed production authority")

    target = negative_inventory.get("target_performer_id")
    if not isinstance(target, str) or not target.strip():
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory target performer is invalid")
    bank_target = bank.get("performer_id")
    if not isinstance(bank_target, str) or target.strip() != bank_target.strip():
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory/bank performer mismatch")
    if plan.get("target_performer_id") != target.strip():
        raise PhotorealIdentityCalibrationAuthorityError("identity negative inventory/plan performer mismatch")

    expected = _sha(plan.get("negative_inventory_sha256"), label="plan negative inventory SHA-256")
    try:
        observed = canonical_identity_negative_inventory_sha256(negative_inventory)
    except PhotorealIdentityNegativeVerifyError as exc:
        raise PhotorealIdentityCalibrationAuthorityError(str(exc)) from exc
    if observed != expected:
        raise PhotorealIdentityCalibrationAuthorityError(
            "identity negative inventory canonical digest mismatch at calibration authority boundary"
        )
    return observed


def build_identity_calibration_authorized(
    bank: Mapping[str, Any],
    plan: Mapping[str, Any],
    negative_observations: Mapping[str, Any],
    negative_inventory: Mapping[str, Any],
) -> dict[str, Any]:
    validate_negative_inventory_binding(negative_inventory, plan, bank)
    return build_identity_calibration(bank, plan, negative_observations)


def build_identity_calibration_authorized_files(
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
    result = build_identity_calibration_authorized(bank, plan, observations, inventory)

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealIdentityCalibrationAuthorityError(f"identity calibration output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
