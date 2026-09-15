from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_animation_plan import ANIMATION_REQUIREMENTS, FORMAT, VERSION

TOP_FIELDS = {
    "format",
    "version",
    "performer_id",
    "selected_epoch_id",
    "teacher_input_sha256",
    "teacher_manifest_sha256",
    "static_teacher_review_sha256",
    "review_render_set_sha256",
    "static_teacher_photoreal_accepted",
    "p1_human_acceptance_required_and_verified",
    "teacher_artifact_count",
    "teacher_artifacts",
    "teacher_artifact_bytes_reverified",
    "animation_model_policy",
    "body_correspondence_policy",
    "face_control_policy",
    "required_validation_dimensions",
    "required_validation_dimension_count",
    "animation_adapter_required",
    "animation_adapter_selected",
    "p2_animation_execution_authorized",
    "animated_teacher_acceptance_authority",
    "human_animated_visual_acceptance_required",
    "p3_device_distillation_authorized",
    "build_only",
    "runtime_dependency",
    "production_activation",
    "animation_plan_sha256",
}
ARTIFACT_FIELDS = {"kind", "relative_path", "size_bytes", "sha256"}


class PhotorealAnimationAuthorityError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimationAuthorityError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealAnimationAuthorityError(f"{label} is invalid")
    return clean


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimationAuthorityError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum:
        raise PhotorealAnimationAuthorityError(f"{label} is invalid")
    return clean


def _digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "animation_plan_sha256"}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _relative_path(value: Any) -> str:
    clean = _text(value, label="teacher artifact relative path").replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealAnimationAuthorityError("teacher artifact relative path escapes its root")
    return clean


def validate_animation_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != TOP_FIELDS:
        raise PhotorealAnimationAuthorityError("animation plan fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != FORMAT or isinstance(version, bool) or not isinstance(version, (int, float)):
        raise PhotorealAnimationAuthorityError("animation plan format/version mismatch")
    if not math.isfinite(float(version)) or version != VERSION:
        raise PhotorealAnimationAuthorityError("animation plan format/version mismatch")

    _text(value.get("performer_id"), label="animation performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="animation selected epoch id", maximum=256)
    for key in (
        "teacher_input_sha256",
        "teacher_manifest_sha256",
        "static_teacher_review_sha256",
        "review_render_set_sha256",
    ):
        _sha(value.get(key), label=key)

    if value.get("static_teacher_photoreal_accepted") is not True:
        raise PhotorealAnimationAuthorityError("animation plan lacks accepted static teacher authority")
    if value.get("p1_human_acceptance_required_and_verified") is not True:
        raise PhotorealAnimationAuthorityError("animation plan lacks verified P1 human acceptance")
    if value.get("teacher_artifact_bytes_reverified") is not True:
        raise PhotorealAnimationAuthorityError("animation plan teacher artifact bytes were not reverified")

    artifacts = value.get("teacher_artifacts")
    count = value.get("teacher_artifact_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise PhotorealAnimationAuthorityError("teacher_artifact_count is invalid")
    if not isinstance(artifacts, list) or len(artifacts) != count:
        raise PhotorealAnimationAuthorityError("teacher_artifact_count does not match teacher_artifacts")
    seen: set[str] = set()
    normalized_artifacts: list[dict[str, Any]] = []
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != ARTIFACT_FIELDS:
            raise PhotorealAnimationAuthorityError("animation plan teacher artifact fields must match v1 exactly")
        kind = _text(raw.get("kind"), label="teacher artifact kind", maximum=64)
        relative = _relative_path(raw.get("relative_path"))
        if relative in seen:
            raise PhotorealAnimationAuthorityError("animation plan repeats teacher artifact path")
        seen.add(relative)
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1:
            raise PhotorealAnimationAuthorityError("teacher artifact size_bytes is invalid")
        normalized_artifacts.append(
            {
                "kind": kind,
                "relative_path": relative,
                "size_bytes": size,
                "sha256": _sha(raw.get("sha256"), label="teacher artifact SHA-256"),
            }
        )

    if value.get("animation_model_policy") != "rig-drives-teacher-does-not-replace-teacher-v1":
        raise PhotorealAnimationAuthorityError("animation model policy mismatch")
    if value.get("body_correspondence_policy") != "canonical-skeleton-smplx-correspondence-v1":
        raise PhotorealAnimationAuthorityError("body correspondence policy mismatch")
    if value.get("face_control_policy") != "explicit-facial-expression-representation-v1":
        raise PhotorealAnimationAuthorityError("face control policy mismatch")

    dimensions = value.get("required_validation_dimensions")
    dimension_count = value.get("required_validation_dimension_count")
    if isinstance(dimension_count, bool) or not isinstance(dimension_count, int):
        raise PhotorealAnimationAuthorityError("required_validation_dimension_count is invalid")
    if dimensions != list(ANIMATION_REQUIREMENTS) or dimension_count != len(ANIMATION_REQUIREMENTS):
        raise PhotorealAnimationAuthorityError("animation validation dimension universe is not canonical")

    if value.get("animation_adapter_required") is not True:
        raise PhotorealAnimationAuthorityError("animation plan does not require an adapter")
    if value.get("animation_adapter_selected") is not False:
        raise PhotorealAnimationAuthorityError("animation plan prematurely selected an adapter")
    if value.get("p2_animation_execution_authorized") is not True:
        raise PhotorealAnimationAuthorityError("animation execution is not authorized")
    if value.get("animated_teacher_acceptance_authority") is not False:
        raise PhotorealAnimationAuthorityError("animation plan prematurely granted animated-teacher acceptance")
    if value.get("human_animated_visual_acceptance_required") is not True:
        raise PhotorealAnimationAuthorityError("animation plan removed human animated visual acceptance")
    if value.get("p3_device_distillation_authorized") is not False:
        raise PhotorealAnimationAuthorityError("animation plan prematurely authorized P3 distillation")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise PhotorealAnimationAuthorityError("animation plan build/runtime boundary is invalid")
    if value.get("production_activation") is not False:
        raise PhotorealAnimationAuthorityError("animation plan crossed production authority")

    declared = _sha(value.get("animation_plan_sha256"), label="animation plan SHA-256")
    if declared != _digest(value):
        raise PhotorealAnimationAuthorityError("animation plan SHA-256 does not match plan content")

    result = dict(value)
    result["teacher_artifacts"] = normalized_artifacts
    return result


def read_animation_plan(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAnimationAuthorityError(f"animation plan is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAnimationAuthorityError("animation plan must be a JSON object")
    return validate_animation_plan(value)


def require_animation_execution_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_animation_plan(value)
    if validated["p2_animation_execution_authorized"] is not True:
        raise PhotorealAnimationAuthorityError("P2 animation execution is not authorized")
    return validated
