from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_animated_teacher_review_authority import (
    PhotorealAnimatedTeacherReviewAuthorityError,
    require_p3_device_distillation_authority,
)
from .photoreal_animation_execution_receipt import (
    PhotorealAnimationExecutionReceiptError,
    validate_animation_execution_receipt,
)

FORMAT = "bodyrig-photoreal-device-distillation-plan"
VERSION = 1
PROFILE_FORMAT = "bodyrig-photoreal-device-target-profile"
PROFILE_VERSION = 1

TARGET_MODELS = ("quest-2", "quest-3", "quest-3s")
CANDIDATE_REPRESENTATIONS = (
    "skinned-mesh-pbr",
    "skinned-mesh-neural-texture",
    "hybrid-mesh-neural-residual",
    "specialized-eye-component",
    "teacher-derived-hair-component",
    "gaussian-splat-optional",
)
FIDELITY_DIMENSIONS = (
    "identity_likeness",
    "face_detail",
    "eyes",
    "hair_silhouette_and_appearance",
    "skin_material_response",
    "hands_and_extremities",
    "motion_identity_preservation",
    "temporal_stability",
)

PROFILE_FIELDS = {
    "format",
    "version",
    "operator_supplied",
    "target_family",
    "target_model",
    "target_runtime",
    "target_refresh_hz",
    "max_frame_time_ms",
    "stereo_rendering_required",
    "vr_safe_frame_pacing_required",
    "teacher_quality_ceiling_preserved",
    "fidelity_delta_reporting_required",
    "production_activation",
}


class PhotorealDeviceDistillationPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealDeviceDistillationPlanError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealDeviceDistillationPlanError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceDistillationPlanError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealDeviceDistillationPlanError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealDeviceDistillationPlanError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealDeviceDistillationPlanError(f"{label} is invalid")
    return clean


def _v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealDeviceDistillationPlanError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealDeviceDistillationPlanError(f"{label} version must be numeric v1")


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _digest_without(value: Mapping[str, Any], key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _safe_child(root: Path, relative: Any) -> tuple[str, Path]:
    clean = _text(relative, label="animation artifact relative path").replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealDeviceDistillationPlanError("animation artifact path escapes output root")
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealDeviceDistillationPlanError("animation artifact path escapes output root") from exc
    return clean, target


def validate_device_target_profile(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != PROFILE_FIELDS:
        raise PhotorealDeviceDistillationPlanError("device target profile fields must match v1 exactly")
    if value.get("format") != PROFILE_FORMAT:
        raise PhotorealDeviceDistillationPlanError("device target profile format mismatch")
    _v1(value.get("version"), label="device target profile")
    if value.get("operator_supplied") is not True:
        raise PhotorealDeviceDistillationPlanError("device target profile must be operator supplied")
    if value.get("target_family") != "meta-quest":
        raise PhotorealDeviceDistillationPlanError("device target family is unsupported")
    model = value.get("target_model")
    if model not in TARGET_MODELS:
        raise PhotorealDeviceDistillationPlanError("device target model is unsupported")
    if value.get("target_runtime") != "standalone":
        raise PhotorealDeviceDistillationPlanError("device target runtime must be standalone")
    refresh = value.get("target_refresh_hz")
    if isinstance(refresh, bool) or not isinstance(refresh, (int, float)):
        raise PhotorealDeviceDistillationPlanError("target refresh rate is invalid")
    refresh_value = float(refresh)
    if not math.isfinite(refresh_value) or not 30.0 <= refresh_value <= 240.0:
        raise PhotorealDeviceDistillationPlanError("target refresh rate is outside the planning safety range")
    refresh_value = round(refresh_value, 6)
    frame_time = value.get("max_frame_time_ms")
    if isinstance(frame_time, bool) or not isinstance(frame_time, (int, float)):
        raise PhotorealDeviceDistillationPlanError("target frame-time budget is invalid")
    frame_time_value = round(float(frame_time), 6)
    if not math.isfinite(frame_time_value) or frame_time_value <= 0:
        raise PhotorealDeviceDistillationPlanError("target frame-time budget is invalid")
    expected = round(1000.0 / refresh_value, 6)
    if frame_time_value != expected:
        raise PhotorealDeviceDistillationPlanError("target frame-time budget must equal 1000/target_refresh_hz")
    for key in (
        "stereo_rendering_required",
        "vr_safe_frame_pacing_required",
        "teacher_quality_ceiling_preserved",
        "fidelity_delta_reporting_required",
    ):
        if value.get(key) is not True:
            raise PhotorealDeviceDistillationPlanError(f"device target profile requirement is missing: {key}")
    if value.get("production_activation") is not False:
        raise PhotorealDeviceDistillationPlanError("device target profile crossed production authority")
    return {
        "format": PROFILE_FORMAT,
        "version": PROFILE_VERSION,
        "operator_supplied": True,
        "target_family": "meta-quest",
        "target_model": str(model),
        "target_runtime": "standalone",
        "target_refresh_hz": refresh_value,
        "max_frame_time_ms": frame_time_value,
        "stereo_rendering_required": True,
        "vr_safe_frame_pacing_required": True,
        "teacher_quality_ceiling_preserved": True,
        "fidelity_delta_reporting_required": True,
        "production_activation": False,
    }


def build_device_distillation_plan(
    animated_teacher_review: Mapping[str, Any],
    animation_execution_receipt: Mapping[str, Any],
    target_profile: Mapping[str, Any],
    *,
    animation_output_root: str | Path,
) -> dict[str, Any]:
    try:
        review = require_p3_device_distillation_authority(animated_teacher_review)
    except PhotorealAnimatedTeacherReviewAuthorityError as exc:
        raise PhotorealDeviceDistillationPlanError(str(exc)) from exc
    try:
        execution = validate_animation_execution_receipt(animation_execution_receipt)
    except PhotorealAnimationExecutionReceiptError as exc:
        raise PhotorealDeviceDistillationPlanError(str(exc)) from exc
    profile = validate_device_target_profile(target_profile)

    if not (
        review["performer_id"] == execution["performer_id"]
        and review["selected_epoch_id"] == execution["selected_epoch_id"]
        and review["teacher_input_sha256"] == execution["teacher_input_sha256"]
        and review["teacher_manifest_sha256"] == execution["teacher_manifest_sha256"]
        and review["static_teacher_review_sha256"] == execution["static_teacher_review_sha256"]
        and review["animation_plan_sha256"] == execution["animation_plan_sha256"]
    ):
        raise PhotorealDeviceDistillationPlanError("P2 human acceptance and animation execution lineage do not match")
    if review["animation_execution_receipt_sha256"] != execution["animation_execution_receipt_sha256"]:
        raise PhotorealDeviceDistillationPlanError("P2 human acceptance targets a different animation execution receipt")

    root = Path(animation_output_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealDeviceDistillationPlanError(f"animation output root not found: {root}")
    artifacts = execution.get("animation_artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealDeviceDistillationPlanError("animation execution receipt has no distillation source artifacts")
    normalized_artifacts: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping):
            raise PhotorealDeviceDistillationPlanError("animation artifact entry is invalid")
        relative, path = _safe_child(root, raw.get("relative_path"))
        if relative in seen:
            raise PhotorealDeviceDistillationPlanError("animation execution repeats distillation source artifact")
        seen.add(relative)
        if not path.is_file():
            raise PhotorealDeviceDistillationPlanError(f"distillation source artifact is missing: {relative}")
        size = raw.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 1 or path.stat().st_size != size:
            raise PhotorealDeviceDistillationPlanError(f"distillation source artifact size drifted: {relative}")
        observed_sha = _hash_file(path)
        declared_sha = _sha(raw.get("sha256"), label="distillation source artifact SHA-256")
        if observed_sha != declared_sha:
            raise PhotorealDeviceDistillationPlanError(f"distillation source artifact bytes drifted: {relative}")
        normalized_artifacts.append(
            {
                "kind": _text(raw.get("kind"), label="distillation source artifact kind", maximum=64),
                "relative_path": relative,
                "size_bytes": size,
                "sha256": observed_sha,
            }
        )
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "animation-manifest.json"
    }
    if actual != seen:
        raise PhotorealDeviceDistillationPlanError("animation output artifact universe drifted before distillation planning")

    profile_sha = _digest_without(profile, "target_profile_sha256")
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": review["performer_id"],
        "selected_epoch_id": review["selected_epoch_id"],
        "teacher_input_sha256": review["teacher_input_sha256"],
        "teacher_manifest_sha256": review["teacher_manifest_sha256"],
        "static_teacher_review_sha256": review["static_teacher_review_sha256"],
        "animation_plan_sha256": review["animation_plan_sha256"],
        "animation_execution_receipt_sha256": review["animation_execution_receipt_sha256"],
        "animated_teacher_review_sha256": review["animated_teacher_review_sha256"],
        "target_profile": profile,
        "target_profile_sha256": profile_sha,
        "distillation_source_artifact_count": len(normalized_artifacts),
        "distillation_source_artifacts": sorted(normalized_artifacts, key=lambda item: item["relative_path"]),
        "source_artifact_bytes_reverified": True,
        "candidate_student_representations": list(CANDIDATE_REPRESENTATIONS),
        "gaussian_splat_requires_explicit_target_support": True,
        "teacher_remains_visual_authority": True,
        "student_may_not_claim_fidelity_above_teacher": True,
        "required_fidelity_delta_dimensions": list(FIDELITY_DIMENSIONS),
        "required_fidelity_delta_dimension_count": len(FIDELITY_DIMENSIONS),
        "fidelity_delta_measurement_required": True,
        "human_runtime_visual_acceptance_required": True,
        "distillation_adapter_required": True,
        "distillation_adapter_selected": False,
        "p3_distillation_execution_authorized": True,
        "runtime_acceptance_authority": False,
        "production_activation": False,
    }
    result["device_distillation_plan_sha256"] = _digest_without(result, "device_distillation_plan_sha256")
    return result


def build_device_distillation_plan_files(
    animated_teacher_review_path: str | Path,
    animation_execution_receipt_path: str | Path,
    target_profile_path: str | Path,
    animation_output_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    review = _read_json(animated_teacher_review_path, label="animated teacher review")
    execution = _read_json(animation_execution_receipt_path, label="animation execution receipt")
    profile = _read_json(target_profile_path, label="device target profile")
    result = build_device_distillation_plan(
        review,
        execution,
        profile,
        animation_output_root=animation_output_root,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealDeviceDistillationPlanError(f"device distillation plan already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
