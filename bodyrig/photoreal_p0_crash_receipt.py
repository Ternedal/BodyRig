from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-photoreal-p0-crash-receipt"
VERSION = 1
MAX_STAGE = 16

P0_OUTPUTS = (
    "source-inventory.json",
    "dataset-plan.json",
    "source-receipt.json",
    "scan-plan.json",
    "identity-bootstrap-plan.json",
    "model-set.json",
    "identity-extractor/output/identity-observations.json",
    "identity-bank.json",
    "identity-negative-inventory.json",
    "identity-negative-receipt.json",
    "identity-calibration-plan.json",
    "identity-calibration-extractor/output/negative-observations.json",
    "identity-calibration.json",
    "frame-measurements.json",
    "frame-authorized-observations.json",
    "frame-index.json",
)

TOP_FIELDS = {
    "format",
    "version",
    "bodyrig_revision",
    "performer_id",
    "failed_stage_number",
    "failed_stage_label",
    "failure_class",
    "error_message",
    "artifact_presence",
    "artifact_present_count",
    "artifact_expected_count",
    "output_root_build_private",
    "partial_outputs_may_not_grant_authority",
    "restart_same_output_root_supported",
    "recovery_action",
    "teacher_training_authorized",
    "photoreal_acceptance_authority",
    "production_activation",
    "p0_crash_receipt_sha256",
}


class PhotorealP0CrashReceiptError(ValueError):
    pass


def _text(value: Any, *, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise PhotorealP0CrashReceiptError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum:
        raise PhotorealP0CrashReceiptError(f"{label} is invalid")
    return clean


def _git_sha(value: Any, *, label: str) -> str:
    clean = _text(value, label=label, maximum=40).lower()
    if len(clean) != 40 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealP0CrashReceiptError(f"{label} must be a 40-character Git SHA")
    return clean


def _v1(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP0CrashReceiptError("crash receipt version must be numeric v1")
    if not math.isfinite(float(value)) or value != VERSION:
        raise PhotorealP0CrashReceiptError("crash receipt version must be numeric v1")


def _digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "p0_crash_receipt_sha256"}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _presence(root: Path) -> dict[str, bool]:
    if not root.is_dir():
        raise PhotorealP0CrashReceiptError(f"P0 output root not found: {root}")
    return {relative: (root / Path(relative)).is_file() for relative in P0_OUTPUTS}


def build_p0_crash_receipt(
    *,
    bodyrig_revision: str,
    performer_id: str,
    failed_stage_number: int,
    failed_stage_label: str,
    error_message: str,
    output_root: str | Path,
) -> dict[str, Any]:
    revision = _git_sha(bodyrig_revision, label="BodyRig revision")
    performer = _text(performer_id, label="performer id", maximum=256)
    if isinstance(failed_stage_number, bool) or not isinstance(failed_stage_number, int):
        raise PhotorealP0CrashReceiptError("failed stage number is invalid")
    if not 0 <= failed_stage_number <= MAX_STAGE:
        raise PhotorealP0CrashReceiptError("failed stage number is outside 0..16")
    stage_label = _text(failed_stage_label, label="failed stage label", maximum=256)
    message = _text(error_message, label="error message", maximum=4000)
    root = Path(output_root).expanduser().resolve()
    presence = _presence(root)
    present_count = sum(1 for present in presence.values() if present)

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "bodyrig_revision": revision,
        "performer_id": performer,
        "failed_stage_number": failed_stage_number,
        "failed_stage_label": stage_label,
        "failure_class": "unexpected-exception",
        "error_message": message,
        "artifact_presence": presence,
        "artifact_present_count": present_count,
        "artifact_expected_count": len(P0_OUTPUTS),
        "output_root_build_private": True,
        "partial_outputs_may_not_grant_authority": True,
        "restart_same_output_root_supported": False,
        "recovery_action": "fix-root-cause-and-run-again-with-a-new-empty-output-root",
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p0_crash_receipt_sha256"] = _digest(result)
    return result


def validate_p0_crash_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != TOP_FIELDS:
        raise PhotorealP0CrashReceiptError("crash receipt fields must match v1 exactly")
    if value.get("format") != FORMAT:
        raise PhotorealP0CrashReceiptError("crash receipt format mismatch")
    _v1(value.get("version"))
    _git_sha(value.get("bodyrig_revision"), label="BodyRig revision")
    _text(value.get("performer_id"), label="performer id", maximum=256)
    stage_number = value.get("failed_stage_number")
    if isinstance(stage_number, bool) or not isinstance(stage_number, int) or not 0 <= stage_number <= MAX_STAGE:
        raise PhotorealP0CrashReceiptError("crash receipt stage number is invalid")
    _text(value.get("failed_stage_label"), label="failed stage label", maximum=256)
    if value.get("failure_class") != "unexpected-exception":
        raise PhotorealP0CrashReceiptError("crash receipt failure class mismatch")
    _text(value.get("error_message"), label="error message", maximum=4000)

    presence = value.get("artifact_presence")
    if not isinstance(presence, Mapping) or set(presence) != set(P0_OUTPUTS):
        raise PhotorealP0CrashReceiptError("crash receipt artifact universe is not canonical")
    if any(type(presence[item]) is not bool for item in P0_OUTPUTS):
        raise PhotorealP0CrashReceiptError("crash receipt artifact presence values must be boolean")
    present_count = sum(1 for item in P0_OUTPUTS if presence[item])
    if value.get("artifact_present_count") != present_count:
        raise PhotorealP0CrashReceiptError("crash receipt artifact present count mismatch")
    if value.get("artifact_expected_count") != len(P0_OUTPUTS):
        raise PhotorealP0CrashReceiptError("crash receipt artifact expected count mismatch")

    for key in ("output_root_build_private", "partial_outputs_may_not_grant_authority"):
        if value.get(key) is not True:
            raise PhotorealP0CrashReceiptError(f"crash receipt boundary mismatch: {key}")
    if value.get("restart_same_output_root_supported") is not False:
        raise PhotorealP0CrashReceiptError("crash receipt may not authorize same-root restart")
    if value.get("recovery_action") != "fix-root-cause-and-run-again-with-a-new-empty-output-root":
        raise PhotorealP0CrashReceiptError("crash receipt recovery action mismatch")
    for key in (
        "teacher_training_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        if value.get(key) is not False:
            raise PhotorealP0CrashReceiptError(f"crash receipt crossed authority boundary: {key}")

    declared = value.get("p0_crash_receipt_sha256")
    if not isinstance(declared, str) or len(declared) != 64 or any(ch not in "0123456789abcdef" for ch in declared):
        raise PhotorealP0CrashReceiptError("crash receipt SHA-256 is invalid")
    if declared != _digest(value):
        raise PhotorealP0CrashReceiptError("crash receipt SHA-256 does not match content")
    return dict(value)


def write_p0_crash_receipt(receipt: Mapping[str, Any], output_path: str | Path) -> dict[str, Any]:
    validated = validate_p0_crash_receipt(receipt)
    path = Path(output_path).expanduser().resolve()
    if path.exists():
        raise PhotorealP0CrashReceiptError(f"P0 crash receipt already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(validated, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return validated


def read_p0_crash_receipt(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealP0CrashReceiptError(f"P0 crash receipt is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealP0CrashReceiptError("P0 crash receipt must be a JSON object")
    return validate_p0_crash_receipt(value)
