from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_static_teacher_review_authority import (
    PhotorealStaticTeacherReviewAuthorityError,
    require_p2_animation_authority,
)

FORMAT = "bodyrig-photoreal-animation-plan"
VERSION = 1
TEACHER_MANIFEST_FORMAT = "bodyrig-photoreal-teacher-manifest"
REVIEW_RENDER_SET_FORMAT = "bodyrig-photoreal-teacher-review-render-set"

TEACHER_MANIFEST_FIELDS = {
    "format",
    "version",
    "performer_id",
    "selected_epoch_id",
    "teacher_input_sha256",
    "adapter",
    "adapter_revision",
    "upstream_repository",
    "upstream_commit",
    "training_complete",
    "consumed_training_source_keys",
    "consumed_training_observations",
    "artifacts",
    "photoreal_acceptance_authority",
    "human_visual_acceptance_required",
    "production_activation",
}
REVIEW_RENDER_SET_FIELDS = {
    "format",
    "version",
    "performer_id",
    "selected_epoch_id",
    "teacher_input_sha256",
    "teacher_manifest_sha256",
    "adapter",
    "upstream_repository",
    "upstream_commit",
    "camera_calibration_source",
    "camera_calibration_formula",
    "render_count",
    "renders",
    "render_bytes_verified",
    "camera_geometry_authority",
    "semantic_view_authority",
    "human_semantic_view_mapping_required",
    "held_out_reference_binding_present",
    "photoreal_acceptance_authority",
    "human_visual_acceptance_required",
    "build_only",
    "runtime_dependency",
    "production_activation",
    "review_render_set_sha256",
}
ANIMATION_REQUIREMENTS = (
    "body_pose_smplx_correspondence",
    "face_expression_control",
    "head_turn_validation",
    "eye_motion_validation",
    "mouth_motion_validation",
    "hand_motion_validation",
    "full_body_pose_validation",
    "identity_appearance_motion_preservation",
)


class PhotorealAnimationPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAnimationPlanError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAnimationPlanError(f"{label} must be a JSON object")
    return value


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimationPlanError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealAnimationPlanError(f"{label} is invalid")
    return clean


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimationPlanError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum:
        raise PhotorealAnimationPlanError(f"{label} is invalid")
    return clean


def _numeric_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealAnimationPlanError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealAnimationPlanError(f"{label} version must be numeric v1")


def _digest_without(value: Mapping[str, Any], key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _safe_artifact_path(root: Path, relative: Any) -> tuple[str, Path]:
    value = _text(relative, label="teacher artifact relative path").replace("\\", "/")
    if value.startswith("/") or value.startswith("../") or "/../" in f"/{value}/" or ":" in value.split("/", 1)[0]:
        raise PhotorealAnimationPlanError("teacher artifact path escapes output root")
    target = (root / Path(value)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealAnimationPlanError("teacher artifact path escapes output root") from exc
    return value, target


def _validate_teacher_manifest(
    value: Mapping[str, Any],
    *,
    teacher_output_root: Path,
) -> tuple[str, str, str, list[dict[str, Any]]]:
    if set(value) != TEACHER_MANIFEST_FIELDS:
        raise PhotorealAnimationPlanError("teacher manifest fields must match v1 exactly")
    if value.get("format") != TEACHER_MANIFEST_FORMAT:
        raise PhotorealAnimationPlanError("teacher manifest format mismatch")
    _numeric_v1(value.get("version"), label="teacher manifest")
    if value.get("training_complete") is not True:
        raise PhotorealAnimationPlanError("teacher manifest does not report complete training")
    if value.get("photoreal_acceptance_authority") is not False:
        raise PhotorealAnimationPlanError("teacher manifest improperly granted photoreal authority")
    if value.get("human_visual_acceptance_required") is not True:
        raise PhotorealAnimationPlanError("teacher manifest removed human visual acceptance")
    if value.get("production_activation") is not False:
        raise PhotorealAnimationPlanError("teacher manifest crossed production authority")

    performer_id = _text(value.get("performer_id"), label="teacher performer id", maximum=256)
    epoch_id = _text(value.get("selected_epoch_id"), label="teacher selected epoch id", maximum=256)
    teacher_input_sha = _sha(value.get("teacher_input_sha256"), label="teacher input SHA-256")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        raise PhotorealAnimationPlanError("teacher manifest contains no artifacts")

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in artifacts:
        if not isinstance(raw, Mapping) or set(raw) != {"kind", "relative_path", "size_bytes", "sha256"}:
            raise PhotorealAnimationPlanError("teacher artifact fields must match v1 exactly")
        kind = _text(raw.get("kind"), label="teacher artifact kind", maximum=64)
        relative, path = _safe_artifact_path(teacher_output_root, raw.get("relative_path"))
        if relative == "teacher-manifest.json" or relative in seen:
            raise PhotorealAnimationPlanError("teacher artifact path is repeated or reserved")
        seen.add(relative)
        if not path.is_file():
            raise PhotorealAnimationPlanError(f"teacher artifact is missing: {relative}")
        observed_size = path.stat().st_size
        declared_size = raw.get("size_bytes")
        if isinstance(declared_size, bool) or not isinstance(declared_size, int) or declared_size < 1:
            raise PhotorealAnimationPlanError(f"teacher artifact size is invalid: {relative}")
        if declared_size != observed_size:
            raise PhotorealAnimationPlanError(f"teacher artifact size mismatch: {relative}")
        observed_sha = _hash_file(path)
        if _sha(raw.get("sha256"), label="teacher artifact SHA-256") != observed_sha:
            raise PhotorealAnimationPlanError(f"teacher artifact SHA-256 mismatch: {relative}")
        normalized.append(
            {
                "kind": kind,
                "relative_path": relative,
                "size_bytes": observed_size,
                "sha256": observed_sha,
            }
        )

    actual_files = {
        path.relative_to(teacher_output_root).as_posix()
        for path in teacher_output_root.rglob("*")
        if path.is_file() and path.name != "teacher-manifest.json"
    }
    if actual_files != seen:
        raise PhotorealAnimationPlanError("teacher artifact universe differs from teacher manifest")
    return performer_id, epoch_id, teacher_input_sha, sorted(normalized, key=lambda item: item["relative_path"])


def _validate_review_render_set(value: Mapping[str, Any]) -> tuple[str, str, str, str]:
    if set(value) != REVIEW_RENDER_SET_FIELDS:
        raise PhotorealAnimationPlanError("review render set fields must match v1 exactly")
    if value.get("format") != REVIEW_RENDER_SET_FORMAT:
        raise PhotorealAnimationPlanError("review render set format mismatch")
    _numeric_v1(value.get("version"), label="review render set")
    declared = _sha(value.get("review_render_set_sha256"), label="review render set SHA-256")
    if declared != _digest_without(value, "review_render_set_sha256"):
        raise PhotorealAnimationPlanError("review render set SHA-256 does not match content")
    if value.get("render_bytes_verified") is not True or value.get("camera_geometry_authority") is not True:
        raise PhotorealAnimationPlanError("review render set lacks byte/camera authority")
    if value.get("photoreal_acceptance_authority") is not False:
        raise PhotorealAnimationPlanError("review render set improperly granted photoreal authority")
    if value.get("human_visual_acceptance_required") is not True:
        raise PhotorealAnimationPlanError("review render set removed human acceptance")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise PhotorealAnimationPlanError("review render set build/runtime boundary is invalid")
    if value.get("production_activation") is not False:
        raise PhotorealAnimationPlanError("review render set crossed production authority")
    return (
        _text(value.get("performer_id"), label="review performer id", maximum=256),
        _text(value.get("selected_epoch_id"), label="review selected epoch id", maximum=256),
        _sha(value.get("teacher_input_sha256"), label="review teacher input SHA-256"),
        _sha(value.get("teacher_manifest_sha256"), label="review teacher manifest SHA-256"),
    )


def build_animation_plan(
    static_review: Mapping[str, Any],
    review_render_set: Mapping[str, Any],
    teacher_manifest: Mapping[str, Any],
    *,
    teacher_output_root: str | Path,
    teacher_manifest_sha256: str,
) -> dict[str, Any]:
    try:
        accepted = require_p2_animation_authority(static_review)
    except PhotorealStaticTeacherReviewAuthorityError as exc:
        raise PhotorealAnimationPlanError(str(exc)) from exc

    root = Path(teacher_output_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealAnimationPlanError(f"teacher output root not found: {root}")
    performer_id, epoch_id, teacher_input_sha, artifacts = _validate_teacher_manifest(
        teacher_manifest,
        teacher_output_root=root,
    )
    review_performer, review_epoch, review_input_sha, review_manifest_sha = _validate_review_render_set(
        review_render_set
    )
    manifest_sha = _sha(teacher_manifest_sha256, label="teacher manifest file SHA-256")
    if manifest_sha != review_manifest_sha:
        raise PhotorealAnimationPlanError("review render set belongs to different teacher manifest bytes")

    if not (
        performer_id == review_performer == accepted["performer_id"]
        and epoch_id == review_epoch == accepted["selected_epoch_id"]
        and teacher_input_sha == review_input_sha == accepted["teacher_input_sha256"]
    ):
        raise PhotorealAnimationPlanError("P1 review and teacher lineage do not match")
    if accepted["review_render_set_sha256"] != review_render_set["review_render_set_sha256"]:
        raise PhotorealAnimationPlanError("P1 acceptance belongs to a different review render set")

    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "selected_epoch_id": epoch_id,
        "teacher_input_sha256": teacher_input_sha,
        "teacher_manifest_sha256": manifest_sha,
        "static_teacher_review_sha256": _sha(
            accepted.get("static_teacher_review_sha256"), label="static teacher review SHA-256"
        ),
        "review_render_set_sha256": _sha(
            review_render_set.get("review_render_set_sha256"), label="review render set SHA-256"
        ),
        "static_teacher_photoreal_accepted": True,
        "p1_human_acceptance_required_and_verified": True,
        "teacher_artifact_count": len(artifacts),
        "teacher_artifacts": artifacts,
        "teacher_artifact_bytes_reverified": True,
        "animation_model_policy": "rig-drives-teacher-does-not-replace-teacher-v1",
        "body_correspondence_policy": "canonical-skeleton-smplx-correspondence-v1",
        "face_control_policy": "explicit-facial-expression-representation-v1",
        "required_validation_dimensions": list(ANIMATION_REQUIREMENTS),
        "required_validation_dimension_count": len(ANIMATION_REQUIREMENTS),
        "animation_adapter_required": True,
        "animation_adapter_selected": False,
        "p2_animation_execution_authorized": True,
        "animated_teacher_acceptance_authority": False,
        "human_animated_visual_acceptance_required": True,
        "p3_device_distillation_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["animation_plan_sha256"] = _digest_without(result, "animation_plan_sha256")
    return result


def build_animation_plan_files(
    static_review_path: str | Path,
    review_render_set_path: str | Path,
    teacher_manifest_path: str | Path,
    teacher_output_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    static_review = _read_json(static_review_path, label="static teacher review")
    review_render_set = _read_json(review_render_set_path, label="teacher review render set")
    manifest_path = Path(teacher_manifest_path).expanduser().resolve()
    teacher_manifest = _read_json(manifest_path, label="teacher manifest")
    result = build_animation_plan(
        static_review,
        review_render_set,
        teacher_manifest,
        teacher_output_root=teacher_output_root,
        teacher_manifest_sha256=_hash_file(manifest_path),
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealAnimationPlanError(f"animation plan already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
