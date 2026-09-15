from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_device_distillation_plan import FIDELITY_DIMENSIONS

FORMAT = "bodyrig-photoreal-device-distillation-execution-receipt"
VERSION = 1
TOP_FIELDS = {
    "format",
    "version",
    "performer_id",
    "selected_epoch_id",
    "teacher_input_sha256",
    "teacher_manifest_sha256",
    "static_teacher_review_sha256",
    "animation_plan_sha256",
    "animation_execution_receipt_sha256",
    "animated_teacher_review_sha256",
    "device_distillation_plan_sha256",
    "target_profile_sha256",
    "adapter",
    "adapter_revision",
    "student_representation",
    "distillation_complete",
    "consumed_distillation_source_artifacts",
    "fidelity_delta_measurements",
    "student_artifacts",
    "artifact_bytes_verified_by_core",
    "student_fidelity_claim_exceeds_teacher",
    "human_runtime_visual_acceptance_required",
    "runtime_acceptance_authority",
    "production_activation",
    "device_distillation_execution_receipt_sha256",
}
ARTIFACT_FIELDS = {"kind", "relative_path", "size_bytes", "sha256"}
CONSUMED_FIELDS = {"relative_path", "sha256"}
MEASUREMENT_FIELDS = {"dimension", "metric", "value", "unit", "teacher_reference", "student_reference"}


class PhotorealDeviceDistillationExecutionReceiptError(ValueError):
    pass


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceDistillationExecutionReceiptError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealDeviceDistillationExecutionReceiptError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceDistillationExecutionReceiptError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealDeviceDistillationExecutionReceiptError(f"{label} is invalid")
    return clean


def _v1(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt version must be numeric v1")
    if not math.isfinite(float(value)) or value != VERSION:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt version must be numeric v1")


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealDeviceDistillationExecutionReceiptError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise PhotorealDeviceDistillationExecutionReceiptError(f"{label} is invalid")
    return result


def _relative_path(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealDeviceDistillationExecutionReceiptError(f"{label} escapes its root")
    return clean


def _digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "device_distillation_execution_receipt_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def build_device_distillation_execution_receipt(validated_result: Mapping[str, Any]) -> dict[str, Any]:
    if validated_result.get("format") != "bodyrig-photoreal-device-distillation-manifest":
        raise PhotorealDeviceDistillationExecutionReceiptError("validated distillation result format mismatch")
    version = validated_result.get("version")
    if isinstance(version, bool) or not isinstance(version, (int, float)) or version != 1:
        raise PhotorealDeviceDistillationExecutionReceiptError("validated distillation result version mismatch")
    if validated_result.get("distillation_complete") is not True:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution is incomplete")
    if validated_result.get("student_fidelity_claim_exceeds_teacher") is not False:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation result claimed student fidelity above teacher")
    if validated_result.get("human_runtime_visual_acceptance_required") is not True:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation result removed human runtime review")
    if validated_result.get("runtime_acceptance_authority") is not False or validated_result.get("production_activation") is not False:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation result crossed runtime/production authority")
    consumed = validated_result.get("consumed_distillation_source_artifacts")
    measurements = validated_result.get("fidelity_delta_measurements")
    artifacts = validated_result.get("student_artifacts")
    if not isinstance(consumed, list) or not consumed or not isinstance(measurements, list) or not measurements or not isinstance(artifacts, list) or not artifacts:
        raise PhotorealDeviceDistillationExecutionReceiptError("validated distillation result lacks provenance/evidence")

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": _text(validated_result.get("performer_id"), label="performer id", maximum=256),
        "selected_epoch_id": _text(validated_result.get("selected_epoch_id"), label="selected epoch id", maximum=256),
        "teacher_input_sha256": _sha(validated_result.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "teacher_manifest_sha256": _sha(validated_result.get("teacher_manifest_sha256"), label="teacher manifest SHA-256"),
        "static_teacher_review_sha256": _sha(validated_result.get("static_teacher_review_sha256"), label="static teacher review SHA-256"),
        "animation_plan_sha256": _sha(validated_result.get("animation_plan_sha256"), label="animation plan SHA-256"),
        "animation_execution_receipt_sha256": _sha(validated_result.get("animation_execution_receipt_sha256"), label="animation execution receipt SHA-256"),
        "animated_teacher_review_sha256": _sha(validated_result.get("animated_teacher_review_sha256"), label="animated teacher review SHA-256"),
        "device_distillation_plan_sha256": _sha(validated_result.get("device_distillation_plan_sha256"), label="device distillation plan SHA-256"),
        "target_profile_sha256": _sha(validated_result.get("target_profile_sha256"), label="target profile SHA-256"),
        "adapter": _text(validated_result.get("adapter"), label="distillation adapter", maximum=80),
        "adapter_revision": _text(validated_result.get("adapter_revision"), label="distillation adapter revision", maximum=160),
        "student_representation": _text(validated_result.get("student_representation"), label="student representation", maximum=160),
        "distillation_complete": True,
        "consumed_distillation_source_artifacts": list(consumed),
        "fidelity_delta_measurements": list(measurements),
        "student_artifacts": list(artifacts),
        "artifact_bytes_verified_by_core": True,
        "student_fidelity_claim_exceeds_teacher": False,
        "human_runtime_visual_acceptance_required": True,
        "runtime_acceptance_authority": False,
        "production_activation": False,
    }
    result["device_distillation_execution_receipt_sha256"] = _digest(result)
    return result


def validate_device_distillation_execution_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != TOP_FIELDS or value.get("format") != FORMAT:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt fields/format mismatch")
    _v1(value.get("version"))
    _text(value.get("performer_id"), label="performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="selected epoch id", maximum=256)
    for key in (
        "teacher_input_sha256",
        "teacher_manifest_sha256",
        "static_teacher_review_sha256",
        "animation_plan_sha256",
        "animation_execution_receipt_sha256",
        "animated_teacher_review_sha256",
        "device_distillation_plan_sha256",
        "target_profile_sha256",
        "device_distillation_execution_receipt_sha256",
    ):
        _sha(value.get(key), label=key)
    _text(value.get("adapter"), label="distillation adapter", maximum=80)
    _text(value.get("adapter_revision"), label="distillation adapter revision", maximum=160)
    _text(value.get("student_representation"), label="student representation", maximum=160)
    if value.get("distillation_complete") is not True:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt is incomplete")

    consumed = value.get("consumed_distillation_source_artifacts")
    if not isinstance(consumed, list) or not consumed:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt has no consumed sources")
    seen_consumed: set[str] = set()
    for raw in consumed:
        if not isinstance(raw, Mapping) or set(raw) != CONSUMED_FIELDS:
            raise PhotorealDeviceDistillationExecutionReceiptError("consumed source artifact fields must match v1 exactly")
        relative = _relative_path(raw.get("relative_path"), label="consumed source artifact path")
        if relative in seen_consumed:
            raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt repeats consumed source")
        seen_consumed.add(relative)
        _sha(raw.get("sha256"), label="consumed source artifact SHA-256")

    measurements = value.get("fidelity_delta_measurements")
    if not isinstance(measurements, list) or len(measurements) != len(FIDELITY_DIMENSIONS):
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt fidelity universe is incomplete")
    seen_dimensions: set[str] = set()
    for index, raw in enumerate(measurements):
        if not isinstance(raw, Mapping) or set(raw) != MEASUREMENT_FIELDS:
            raise PhotorealDeviceDistillationExecutionReceiptError("fidelity delta measurement fields must match v1 exactly")
        dimension = _text(raw.get("dimension"), label="fidelity delta dimension", maximum=80)
        if dimension != FIDELITY_DIMENSIONS[index] or dimension in seen_dimensions:
            raise PhotorealDeviceDistillationExecutionReceiptError("fidelity delta measurement order/universe is not canonical")
        seen_dimensions.add(dimension)
        _text(raw.get("metric"), label="fidelity delta metric", maximum=160)
        _finite(raw.get("value"), label="fidelity delta value")
        _text(raw.get("unit"), label="fidelity delta unit", maximum=80)
        _text(raw.get("teacher_reference"), label="teacher fidelity reference", maximum=512)
        _text(raw.get("student_reference"), label="student fidelity reference", maximum=512)

    artifacts = value.get("student_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt has no student artifacts")
    seen_artifacts: set[str] = set()
    normalized_artifacts: list[dict[str, Any]] = []
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealDeviceDistillationExecutionReceiptError("student artifact fields must match v1 exactly")
        relative = _relative_path(raw.get("relative_path"), label="student artifact path")
        if relative in seen_artifacts:
            raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt repeats student artifact")
        seen_artifacts.add(relative)
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealDeviceDistillationExecutionReceiptError("student artifact size is invalid")
        normalized_artifacts.append(
            {
                "kind": _text(raw.get("kind"), label="student artifact kind", maximum=64),
                "relative_path": relative,
                "size_bytes": size,
                "sha256": _sha(raw.get("sha256"), label="student artifact SHA-256"),
            }
        )
    if artifacts != sorted(normalized_artifacts, key=lambda item: item["relative_path"]):
        raise PhotorealDeviceDistillationExecutionReceiptError("student artifact universe is not canonical")
    if value.get("artifact_bytes_verified_by_core") is not True:
        raise PhotorealDeviceDistillationExecutionReceiptError("student artifact bytes were not core-verified")
    if value.get("student_fidelity_claim_exceeds_teacher") is not False:
        raise PhotorealDeviceDistillationExecutionReceiptError("student fidelity claim exceeds teacher")
    if value.get("human_runtime_visual_acceptance_required") is not True:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt removed human runtime review")
    if value.get("runtime_acceptance_authority") is not False or value.get("production_activation") is not False:
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt crossed runtime/production authority")
    declared = _sha(value.get("device_distillation_execution_receipt_sha256"), label="distillation execution receipt SHA-256")
    if declared != _digest(value):
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt SHA-256 does not match content")
    return dict(value)


def write_device_distillation_execution_receipt(validated_result: Mapping[str, Any], output_path: str | Path) -> dict[str, Any]:
    receipt = build_device_distillation_execution_receipt(validated_result)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealDeviceDistillationExecutionReceiptError(f"distillation execution receipt already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return receipt


def read_device_distillation_execution_receipt(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealDeviceDistillationExecutionReceiptError(f"distillation execution receipt is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealDeviceDistillationExecutionReceiptError("distillation execution receipt must be a JSON object")
    return validate_device_distillation_execution_receipt(value)
