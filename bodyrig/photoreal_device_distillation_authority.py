from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_device_distillation_plan import (
    CANDIDATE_REPRESENTATIONS,
    FIDELITY_DIMENSIONS,
    FORMAT,
    PROFILE_FIELDS,
    PROFILE_FORMAT,
    PROFILE_VERSION,
    TARGET_MODELS,
    VERSION,
)

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
    "target_profile",
    "target_profile_sha256",
    "distillation_source_artifact_count",
    "distillation_source_artifacts",
    "source_artifact_bytes_reverified",
    "candidate_student_representations",
    "gaussian_splat_requires_explicit_target_support",
    "teacher_remains_visual_authority",
    "student_may_not_claim_fidelity_above_teacher",
    "required_fidelity_delta_dimensions",
    "required_fidelity_delta_dimension_count",
    "fidelity_delta_measurement_required",
    "human_runtime_visual_acceptance_required",
    "distillation_adapter_required",
    "distillation_adapter_selected",
    "p3_distillation_execution_authorized",
    "runtime_acceptance_authority",
    "production_activation",
    "device_distillation_plan_sha256",
}
ARTIFACT_FIELDS = {"kind", "relative_path", "size_bytes", "sha256"}


class PhotorealDeviceDistillationAuthorityError(ValueError):
    pass


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceDistillationAuthorityError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealDeviceDistillationAuthorityError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceDistillationAuthorityError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealDeviceDistillationAuthorityError(f"{label} is invalid")
    return clean


def _v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealDeviceDistillationAuthorityError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealDeviceDistillationAuthorityError(f"{label} version must be numeric v1")


def _digest_without(value: Mapping[str, Any], key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _relative_path(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealDeviceDistillationAuthorityError(f"{label} escapes its root")
    return clean


def _validate_profile(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != PROFILE_FIELDS or value.get("format") != PROFILE_FORMAT:
        raise PhotorealDeviceDistillationAuthorityError("device target profile fields/format mismatch")
    _v1(value.get("version"), label="device target profile")
    if value.get("operator_supplied") is not True:
        raise PhotorealDeviceDistillationAuthorityError("device target profile is not operator supplied")
    if value.get("target_family") != "meta-quest" or value.get("target_model") not in TARGET_MODELS:
        raise PhotorealDeviceDistillationAuthorityError("device target family/model is unsupported")
    if value.get("target_runtime") != "standalone":
        raise PhotorealDeviceDistillationAuthorityError("device target runtime must be standalone")
    refresh = value.get("target_refresh_hz")
    frame_time = value.get("max_frame_time_ms")
    if isinstance(refresh, bool) or not isinstance(refresh, (int, float)):
        raise PhotorealDeviceDistillationAuthorityError("device target refresh rate is invalid")
    if isinstance(frame_time, bool) or not isinstance(frame_time, (int, float)):
        raise PhotorealDeviceDistillationAuthorityError("device target frame-time budget is invalid")
    refresh_value = float(refresh)
    frame_time_value = float(frame_time)
    if not math.isfinite(refresh_value) or not 30.0 <= refresh_value <= 240.0:
        raise PhotorealDeviceDistillationAuthorityError("device target refresh rate is invalid")
    if not math.isfinite(frame_time_value) or frame_time_value <= 0:
        raise PhotorealDeviceDistillationAuthorityError("device target frame-time budget is invalid")
    if round(frame_time_value, 6) != round(1000.0 / refresh_value, 6):
        raise PhotorealDeviceDistillationAuthorityError("device target frame-time budget does not match refresh rate")
    for key in (
        "stereo_rendering_required",
        "vr_safe_frame_pacing_required",
        "teacher_quality_ceiling_preserved",
        "fidelity_delta_reporting_required",
    ):
        if value.get(key) is not True:
            raise PhotorealDeviceDistillationAuthorityError(f"device target profile requirement missing: {key}")
    if value.get("production_activation") is not False:
        raise PhotorealDeviceDistillationAuthorityError("device target profile crossed production authority")
    return dict(value)


def validate_device_distillation_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != TOP_FIELDS or value.get("format") != FORMAT:
        raise PhotorealDeviceDistillationAuthorityError("device distillation plan fields/format mismatch")
    _v1(value.get("version"), label="device distillation plan")
    _text(value.get("performer_id"), label="distillation performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="distillation epoch id", maximum=256)
    for key in (
        "teacher_input_sha256",
        "teacher_manifest_sha256",
        "static_teacher_review_sha256",
        "animation_plan_sha256",
        "animation_execution_receipt_sha256",
        "animated_teacher_review_sha256",
        "target_profile_sha256",
        "device_distillation_plan_sha256",
    ):
        _sha(value.get(key), label=key)

    profile = value.get("target_profile")
    if not isinstance(profile, Mapping):
        raise PhotorealDeviceDistillationAuthorityError("device target profile is invalid")
    normalized_profile = _validate_profile(profile)
    if value.get("target_profile_sha256") != _digest_without(normalized_profile, "target_profile_sha256"):
        raise PhotorealDeviceDistillationAuthorityError("device target profile SHA-256 does not match content")

    artifacts = value.get("distillation_source_artifacts")
    count = value.get("distillation_source_artifact_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise PhotorealDeviceDistillationAuthorityError("distillation source artifact count is invalid")
    if not isinstance(artifacts, list) or len(artifacts) != count:
        raise PhotorealDeviceDistillationAuthorityError("distillation source artifact count mismatch")
    normalized_artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealDeviceDistillationAuthorityError("distillation source artifact fields must match v1 exactly")
        relative = _relative_path(raw.get("relative_path"), label="distillation source artifact path")
        if relative in seen:
            raise PhotorealDeviceDistillationAuthorityError("device distillation plan repeats source artifact")
        seen.add(relative)
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealDeviceDistillationAuthorityError("distillation source artifact size is invalid")
        normalized_artifacts.append(
            {
                "kind": _text(raw.get("kind"), label="distillation source artifact kind", maximum=64),
                "relative_path": relative,
                "size_bytes": size,
                "sha256": _sha(raw.get("sha256"), label="distillation source artifact SHA-256"),
            }
        )
    if artifacts != sorted(normalized_artifacts, key=lambda item: item["relative_path"]):
        raise PhotorealDeviceDistillationAuthorityError("distillation source artifact universe is not canonical")

    if value.get("source_artifact_bytes_reverified") is not True:
        raise PhotorealDeviceDistillationAuthorityError("distillation source bytes were not reverified")
    if value.get("candidate_student_representations") != list(CANDIDATE_REPRESENTATIONS):
        raise PhotorealDeviceDistillationAuthorityError("student representation candidate universe is not canonical")
    if value.get("required_fidelity_delta_dimensions") != list(FIDELITY_DIMENSIONS):
        raise PhotorealDeviceDistillationAuthorityError("fidelity delta dimension universe is not canonical")
    dimension_count = value.get("required_fidelity_delta_dimension_count")
    if isinstance(dimension_count, bool) or dimension_count != len(FIDELITY_DIMENSIONS):
        raise PhotorealDeviceDistillationAuthorityError("fidelity delta dimension count mismatch")
    for key in (
        "gaussian_splat_requires_explicit_target_support",
        "teacher_remains_visual_authority",
        "student_may_not_claim_fidelity_above_teacher",
        "fidelity_delta_measurement_required",
        "human_runtime_visual_acceptance_required",
        "distillation_adapter_required",
        "p3_distillation_execution_authorized",
    ):
        if value.get(key) is not True:
            raise PhotorealDeviceDistillationAuthorityError(f"device distillation authority requirement missing: {key}")
    if value.get("distillation_adapter_selected") is not False:
        raise PhotorealDeviceDistillationAuthorityError("device distillation plan prematurely selected an adapter")
    if value.get("runtime_acceptance_authority") is not False:
        raise PhotorealDeviceDistillationAuthorityError("device distillation plan prematurely granted runtime acceptance")
    if value.get("production_activation") is not False:
        raise PhotorealDeviceDistillationAuthorityError("device distillation plan crossed production authority")

    declared = _sha(value.get("device_distillation_plan_sha256"), label="device distillation plan SHA-256")
    if declared != _digest_without(value, "device_distillation_plan_sha256"):
        raise PhotorealDeviceDistillationAuthorityError("device distillation plan SHA-256 does not match content")
    return dict(value)


def require_distillation_execution_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_device_distillation_plan(value)
    if validated["p3_distillation_execution_authorized"] is not True:
        raise PhotorealDeviceDistillationAuthorityError("P3 distillation execution is not authorized")
    return validated


def read_device_distillation_plan(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealDeviceDistillationAuthorityError(f"device distillation plan is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealDeviceDistillationAuthorityError("device distillation plan must be a JSON object")
    return validate_device_distillation_plan(value)
