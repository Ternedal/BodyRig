from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_animation_plan import ANIMATION_REQUIREMENTS

FORMAT = "bodyrig-photoreal-animation-execution-receipt"
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
    "adapter",
    "adapter_revision",
    "representation",
    "animation_complete",
    "consumed_teacher_artifacts",
    "implemented_validation_dimensions",
    "animation_artifacts",
    "artifact_bytes_verified_by_core",
    "animated_teacher_acceptance_authority",
    "human_animated_visual_acceptance_required",
    "p3_device_distillation_authorized",
    "production_activation",
    "animation_execution_receipt_sha256",
}
ARTIFACT_FIELDS = {"kind", "relative_path", "size_bytes", "sha256"}
CONSUMED_FIELDS = {"relative_path", "sha256"}


class PhotorealAnimationExecutionReceiptError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimationExecutionReceiptError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealAnimationExecutionReceiptError(f"{label} is invalid")
    return clean


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimationExecutionReceiptError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum:
        raise PhotorealAnimationExecutionReceiptError(f"{label} is invalid")
    return clean


def _numeric_v1(value: Any) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt version must be numeric v1")
    if not math.isfinite(float(value)) or value != VERSION:
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt version must be numeric v1")


def _digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "animation_execution_receipt_sha256"}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def build_animation_execution_receipt(validated_result: Mapping[str, Any]) -> dict[str, Any]:
    if validated_result.get("format") != "bodyrig-photoreal-animation-manifest":
        raise PhotorealAnimationExecutionReceiptError("validated animation result format mismatch")
    version = validated_result.get("version")
    if isinstance(version, bool) or not isinstance(version, (int, float)) or version != 1:
        raise PhotorealAnimationExecutionReceiptError("validated animation result version mismatch")
    if validated_result.get("animation_complete") is not True:
        raise PhotorealAnimationExecutionReceiptError("animation execution is incomplete")
    if validated_result.get("implemented_validation_dimensions") != list(ANIMATION_REQUIREMENTS):
        raise PhotorealAnimationExecutionReceiptError("animation execution validation universe is incomplete")
    if validated_result.get("animated_teacher_acceptance_authority") is not False:
        raise PhotorealAnimationExecutionReceiptError("animation result crossed animated-teacher authority")
    if validated_result.get("human_animated_visual_acceptance_required") is not True:
        raise PhotorealAnimationExecutionReceiptError("animation result removed human animated review")
    if validated_result.get("p3_device_distillation_authorized") is not False:
        raise PhotorealAnimationExecutionReceiptError("animation result prematurely authorized P3")
    if validated_result.get("production_activation") is not False:
        raise PhotorealAnimationExecutionReceiptError("animation result crossed production authority")

    consumed = validated_result.get("consumed_teacher_artifacts")
    artifacts = validated_result.get("animation_artifacts")
    if not isinstance(consumed, list) or not consumed or not isinstance(artifacts, list) or not artifacts:
        raise PhotorealAnimationExecutionReceiptError("validated animation result lacks artifact provenance")

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": _text(validated_result.get("performer_id"), label="performer id", maximum=256),
        "selected_epoch_id": _text(validated_result.get("selected_epoch_id"), label="selected epoch id", maximum=256),
        "teacher_input_sha256": _sha(validated_result.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "teacher_manifest_sha256": _sha(validated_result.get("teacher_manifest_sha256"), label="teacher manifest SHA-256"),
        "static_teacher_review_sha256": _sha(validated_result.get("static_teacher_review_sha256"), label="static teacher review SHA-256"),
        "animation_plan_sha256": _sha(validated_result.get("animation_plan_sha256"), label="animation plan SHA-256"),
        "adapter": _text(validated_result.get("adapter"), label="animation adapter", maximum=80),
        "adapter_revision": _text(validated_result.get("adapter_revision"), label="animation adapter revision", maximum=160),
        "representation": _text(validated_result.get("representation"), label="animation representation", maximum=160),
        "animation_complete": True,
        "consumed_teacher_artifacts": list(consumed),
        "implemented_validation_dimensions": list(ANIMATION_REQUIREMENTS),
        "animation_artifacts": list(artifacts),
        "artifact_bytes_verified_by_core": True,
        "animated_teacher_acceptance_authority": False,
        "human_animated_visual_acceptance_required": True,
        "p3_device_distillation_authorized": False,
        "production_activation": False,
    }
    result["animation_execution_receipt_sha256"] = _digest(result)
    return result


def validate_animation_execution_receipt(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != TOP_FIELDS:
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt fields must match v1 exactly")
    if value.get("format") != FORMAT:
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt format mismatch")
    _numeric_v1(value.get("version"))
    for key in (
        "teacher_input_sha256",
        "teacher_manifest_sha256",
        "static_teacher_review_sha256",
        "animation_plan_sha256",
    ):
        _sha(value.get(key), label=key)
    _text(value.get("performer_id"), label="performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="selected epoch id", maximum=256)
    _text(value.get("adapter"), label="animation adapter", maximum=80)
    _text(value.get("adapter_revision"), label="animation adapter revision", maximum=160)
    _text(value.get("representation"), label="animation representation", maximum=160)
    if value.get("animation_complete") is not True:
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt is incomplete")
    if value.get("implemented_validation_dimensions") != list(ANIMATION_REQUIREMENTS):
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt validation universe is incomplete")
    consumed = value.get("consumed_teacher_artifacts")
    if not isinstance(consumed, list) or not consumed:
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt has no consumed teacher artifacts")
    seen_consumed: set[str] = set()
    for raw in consumed:
        if not isinstance(raw, Mapping) or set(raw) != CONSUMED_FIELDS:
            raise PhotorealAnimationExecutionReceiptError("consumed teacher artifact fields must match v1 exactly")
        relative = _text(raw.get("relative_path"), label="consumed teacher artifact relative path")
        if relative in seen_consumed:
            raise PhotorealAnimationExecutionReceiptError("animation execution receipt repeats consumed teacher artifact")
        seen_consumed.add(relative)
        _sha(raw.get("sha256"), label="consumed teacher artifact SHA-256")
    artifacts = value.get("animation_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt has no animation artifacts")
    seen_artifacts: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealAnimationExecutionReceiptError("animation artifact fields must match v1 exactly")
        _text(raw.get("kind"), label="animation artifact kind", maximum=64)
        relative = _text(raw.get("relative_path"), label="animation artifact relative path")
        if relative in seen_artifacts:
            raise PhotorealAnimationExecutionReceiptError("animation execution receipt repeats animation artifact")
        seen_artifacts.add(relative)
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealAnimationExecutionReceiptError("animation artifact size is invalid")
        _sha(raw.get("sha256"), label="animation artifact SHA-256")
    if value.get("artifact_bytes_verified_by_core") is not True:
        raise PhotorealAnimationExecutionReceiptError("animation artifact bytes were not core-verified")
    if value.get("animated_teacher_acceptance_authority") is not False:
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt crossed acceptance authority")
    if value.get("human_animated_visual_acceptance_required") is not True:
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt removed human review")
    if value.get("p3_device_distillation_authorized") is not False:
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt prematurely authorized P3")
    if value.get("production_activation") is not False:
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt crossed production authority")
    declared = _sha(value.get("animation_execution_receipt_sha256"), label="animation execution receipt SHA-256")
    if declared != _digest(value):
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt SHA-256 does not match content")
    return dict(value)


def write_animation_execution_receipt(
    validated_result: Mapping[str, Any],
    output_path: str | Path,
) -> dict[str, Any]:
    result = build_animation_execution_receipt(validated_result)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealAnimationExecutionReceiptError(f"animation execution receipt already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def read_animation_execution_receipt(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAnimationExecutionReceiptError(f"animation execution receipt is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAnimationExecutionReceiptError("animation execution receipt must be a JSON object")
    return validate_animation_execution_receipt(value)
