from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_device_distillation_execution_receipt import MEASUREMENT_FIELDS
from .photoreal_device_distillation_plan import FIDELITY_DIMENSIONS, PROFILE_FIELDS, PROFILE_FORMAT, TARGET_MODELS
from .photoreal_device_runtime_review_plan import FORMAT, VERSION

TOP_FIELDS = {
    "format", "version", "performer_id", "selected_epoch_id", "teacher_input_sha256",
    "teacher_manifest_sha256", "static_teacher_review_sha256", "animation_plan_sha256",
    "animation_execution_receipt_sha256", "animated_teacher_review_sha256",
    "device_distillation_plan_sha256", "device_distillation_execution_receipt_sha256",
    "target_profile", "target_profile_sha256", "student_representation", "student_artifact_count",
    "student_artifacts", "student_artifact_bytes_reverified", "fidelity_delta_measurements",
    "teacher_remains_visual_authority", "student_fidelity_claim_exceeds_teacher",
    "physical_device_evidence_required", "physical_device_evidence_present",
    "human_runtime_visual_acceptance_required", "runtime_review_ready",
    "runtime_acceptance_authority", "production_activation", "device_runtime_review_plan_sha256",
}
ARTIFACT_FIELDS = {"kind", "relative_path", "size_bytes", "sha256"}


class PhotorealDeviceRuntimeReviewAuthorityError(ValueError):
    pass


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceRuntimeReviewAuthorityError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealDeviceRuntimeReviewAuthorityError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceRuntimeReviewAuthorityError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealDeviceRuntimeReviewAuthorityError(f"{label} is invalid")
    return clean


def _v1(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealDeviceRuntimeReviewAuthorityError("device runtime review plan version must be numeric v1")
    if not math.isfinite(float(value)) or value != VERSION:
        raise PhotorealDeviceRuntimeReviewAuthorityError("device runtime review plan version must be numeric v1")


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealDeviceRuntimeReviewAuthorityError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise PhotorealDeviceRuntimeReviewAuthorityError(f"{label} is invalid")
    return result


def _digest_without(value: Mapping[str, Any], key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _relative_path(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealDeviceRuntimeReviewAuthorityError(f"{label} escapes its root")
    return clean


def _validate_profile(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != PROFILE_FIELDS or value.get("format") != PROFILE_FORMAT:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target profile fields/format mismatch")
    version = value.get("version")
    if isinstance(version, bool) or not isinstance(version, (int, float)) or version != 1:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target profile version mismatch")
    if value.get("operator_supplied") is not True:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target profile is not operator supplied")
    if value.get("target_family") != "meta-quest" or value.get("target_model") not in TARGET_MODELS:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target profile family/model mismatch")
    if value.get("target_runtime") != "standalone":
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target runtime must be standalone")
    refresh = value.get("target_refresh_hz")
    frame_time = value.get("max_frame_time_ms")
    if isinstance(refresh, bool) or not isinstance(refresh, (int, float)) or isinstance(frame_time, bool) or not isinstance(frame_time, (int, float)):
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target timing budget is invalid")
    refresh_value = float(refresh)
    frame_time_value = float(frame_time)
    if not math.isfinite(refresh_value) or not math.isfinite(frame_time_value) or refresh_value <= 0 or frame_time_value <= 0:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target timing budget is invalid")
    if round(frame_time_value, 6) != round(1000.0 / refresh_value, 6):
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target timing budget is inconsistent")
    for key in (
        "stereo_rendering_required", "vr_safe_frame_pacing_required",
        "teacher_quality_ceiling_preserved", "fidelity_delta_reporting_required",
    ):
        if value.get(key) is not True:
            raise PhotorealDeviceRuntimeReviewAuthorityError(f"runtime review target requirement missing: {key}")
    if value.get("production_activation") is not False:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target profile crossed production authority")
    return dict(value)


def validate_device_runtime_review_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != TOP_FIELDS or value.get("format") != FORMAT:
        raise PhotorealDeviceRuntimeReviewAuthorityError("device runtime review plan fields/format mismatch")
    _v1(value.get("version"))
    _text(value.get("performer_id"), label="runtime review performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="runtime review epoch id", maximum=256)
    for key in (
        "teacher_input_sha256", "teacher_manifest_sha256", "static_teacher_review_sha256",
        "animation_plan_sha256", "animation_execution_receipt_sha256", "animated_teacher_review_sha256",
        "device_distillation_plan_sha256", "device_distillation_execution_receipt_sha256",
        "target_profile_sha256", "device_runtime_review_plan_sha256",
    ):
        _sha(value.get(key), label=key)

    profile = value.get("target_profile")
    if not isinstance(profile, Mapping):
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target profile is invalid")
    normalized_profile = _validate_profile(profile)
    if value.get("target_profile_sha256") != _digest_without(normalized_profile, "target_profile_sha256"):
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review target profile SHA-256 does not match content")
    _text(value.get("student_representation"), label="student representation", maximum=160)

    artifacts = value.get("student_artifacts")
    count = value.get("student_artifact_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review student artifact count is invalid")
    if not isinstance(artifacts, list) or len(artifacts) != count:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review student artifact count mismatch")
    normalized_artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review student artifact fields must match v1 exactly")
        relative = _relative_path(raw.get("relative_path"), label="runtime review student artifact path")
        if relative in seen:
            raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review plan repeats student artifact")
        seen.add(relative)
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review student artifact size is invalid")
        normalized_artifacts.append({
            "kind": _text(raw.get("kind"), label="runtime review student artifact kind", maximum=64),
            "relative_path": relative,
            "size_bytes": size,
            "sha256": _sha(raw.get("sha256"), label="runtime review student artifact SHA-256"),
        })
    if artifacts != sorted(normalized_artifacts, key=lambda item: item["relative_path"]):
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review student artifact universe is not canonical")
    if value.get("student_artifact_bytes_reverified") is not True:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review student bytes were not reverified")

    measurements = value.get("fidelity_delta_measurements")
    if not isinstance(measurements, list) or len(measurements) != len(FIDELITY_DIMENSIONS):
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review fidelity delta universe is incomplete")
    for index, raw in enumerate(measurements):
        if not isinstance(raw, Mapping) or set(raw) != MEASUREMENT_FIELDS:
            raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review fidelity delta fields must match v1 exactly")
        if raw.get("dimension") != FIDELITY_DIMENSIONS[index]:
            raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review fidelity delta order/universe is not canonical")
        _text(raw.get("metric"), label="runtime review fidelity metric", maximum=160)
        _finite(raw.get("value"), label="runtime review fidelity delta value")
        _text(raw.get("unit"), label="runtime review fidelity unit", maximum=80)
        _text(raw.get("teacher_reference"), label="runtime review teacher reference", maximum=512)
        _text(raw.get("student_reference"), label="runtime review student reference", maximum=512)

    for key in (
        "teacher_remains_visual_authority", "physical_device_evidence_required",
        "human_runtime_visual_acceptance_required", "runtime_review_ready",
    ):
        if value.get(key) is not True:
            raise PhotorealDeviceRuntimeReviewAuthorityError(f"runtime review authority requirement missing: {key}")
    if value.get("student_fidelity_claim_exceeds_teacher") is not False:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review plan claims student fidelity above teacher")
    if value.get("physical_device_evidence_present") is not False:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review plan prematurely claims physical device evidence")
    if value.get("runtime_acceptance_authority") is not False:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review plan prematurely grants runtime acceptance")
    if value.get("production_activation") is not False:
        raise PhotorealDeviceRuntimeReviewAuthorityError("runtime review plan crossed production authority")
    declared = _sha(value.get("device_runtime_review_plan_sha256"), label="device runtime review plan SHA-256")
    if declared != _digest_without(value, "device_runtime_review_plan_sha256"):
        raise PhotorealDeviceRuntimeReviewAuthorityError("device runtime review plan SHA-256 does not match content")
    return dict(value)


def read_device_runtime_review_plan(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealDeviceRuntimeReviewAuthorityError(f"device runtime review plan is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealDeviceRuntimeReviewAuthorityError("device runtime review plan must be a JSON object")
    return validate_device_runtime_review_plan(value)
