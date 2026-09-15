from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_animation_execution_receipt import (
    PhotorealAnimationExecutionReceiptError,
    validate_animation_execution_receipt,
)

FORMAT = "bodyrig-photoreal-animated-review-plan"
VERSION = 1
SELECTION_INPUT_FORMAT = "bodyrig-photoreal-animated-review-selection-input"
REFERENCE_CATALOG_FORMAT = "bodyrig-photoreal-teacher-held-out-reference-catalog"

MOTION_REVIEW_DIMENSIONS = (
    "head_turn_validation",
    "eye_motion_validation",
    "mouth_motion_validation",
    "hand_motion_validation",
    "full_body_pose_validation",
    "identity_appearance_motion_preservation",
)
MIN_WINDOW_SECONDS = 0.25
MAX_WINDOW_SECONDS = 5.0

SELECTION_INPUT_FIELDS = {"format", "version", "reviewer", "operator_supplied", "selections"}
SELECTION_FIELDS = {
    "dimension",
    "animation_artifact_relative_path",
    "reference_observation_id",
    "window_before_seconds",
    "window_after_seconds",
}
REFERENCE_CATALOG_FIELDS = {
    "format",
    "version",
    "performer_id",
    "selected_epoch_id",
    "teacher_input_sha256",
    "held_out_source_count",
    "held_out_observation_count",
    "held_out_sources",
    "held_out_observations",
    "required_coverage",
    "observed_coverage",
    "coverage_candidates",
    "coverage_authority",
    "teacher_process_disclosure",
    "source_paths_build_private",
    "reference_bytes_materialized",
    "reference_frame_hashes_verified",
    "human_reference_selection_required",
    "photoreal_acceptance_authority",
    "human_visual_acceptance_required",
    "build_only",
    "runtime_dependency",
    "production_activation",
    "held_out_reference_catalog_sha256",
}
REFERENCE_SOURCE_FIELDS = {
    "source_key",
    "group_id",
    "kind",
    "resolved_path",
    "size_bytes",
    "sha256",
    "width",
    "height",
    "projection",
    "stereo_layout",
}
REFERENCE_OBSERVATION_FIELDS = {
    "observation_id",
    "source_key",
    "group_id",
    "frame_sha256",
    "timestamp_seconds",
    "eye",
    "view_bin",
    "coverage",
    "reference_bytes_materialized",
    "reference_frame_hash_verified",
}


class PhotorealAnimatedReviewPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAnimatedReviewPlanError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAnimatedReviewPlanError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimatedReviewPlanError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum:
        raise PhotorealAnimatedReviewPlanError(f"{label} is invalid")
    return clean


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimatedReviewPlanError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealAnimatedReviewPlanError(f"{label} is invalid")
    return clean


def _numeric_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealAnimatedReviewPlanError(f"{label} version must be numeric v1")
    if not math.isfinite(float(value)) or value != 1:
        raise PhotorealAnimatedReviewPlanError(f"{label} version must be numeric v1")


def _finite_window(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealAnimatedReviewPlanError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result) or not MIN_WINDOW_SECONDS <= result <= MAX_WINDOW_SECONDS:
        raise PhotorealAnimatedReviewPlanError(
            f"{label} must be in {MIN_WINDOW_SECONDS}..{MAX_WINDOW_SECONDS} seconds"
        )
    return round(result, 6)


def _timestamp(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealAnimatedReviewPlanError(f"{label} requires a video timestamp")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise PhotorealAnimatedReviewPlanError(f"{label} requires a nonnegative video timestamp")
    return round(result, 6)


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


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(value: Any, *, label: str) -> str:
    clean = _text(value, label=label).replace("\\", "/")
    first = clean.split("/", 1)[0]
    if clean.startswith("/") or clean.startswith("../") or "/../" in f"/{clean}/" or ":" in first:
        raise PhotorealAnimatedReviewPlanError(f"{label} escapes its root")
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative_path(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealAnimatedReviewPlanError(f"{label} escapes its root") from exc
    return clean, target


def _validate_reference_catalog(value: Mapping[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    if set(value) != REFERENCE_CATALOG_FIELDS:
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog fields must match v1 exactly")
    if value.get("format") != REFERENCE_CATALOG_FORMAT:
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog format mismatch")
    _numeric_v1(value.get("version"), label="held-out reference catalog")
    declared = _sha(
        value.get("held_out_reference_catalog_sha256"), label="held-out reference catalog SHA-256"
    )
    if declared != _digest_without(value, "held_out_reference_catalog_sha256"):
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog SHA-256 does not match content")
    if value.get("coverage_authority") != "core-frame-index-v1":
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog coverage authority mismatch")
    if value.get("teacher_process_disclosure") is not False or value.get("source_paths_build_private") is not True:
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog disclosure boundary is invalid")
    if value.get("photoreal_acceptance_authority") is not False:
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog crossed photoreal authority")
    if value.get("human_visual_acceptance_required") is not True:
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog removed human acceptance")
    if value.get("build_only") is not True or value.get("runtime_dependency") is not False:
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog build/runtime boundary is invalid")
    if value.get("production_activation") is not False:
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog crossed production authority")

    sources_raw = value.get("held_out_sources")
    observations_raw = value.get("held_out_observations")
    if not isinstance(sources_raw, list) or not sources_raw:
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog has no sources")
    if not isinstance(observations_raw, list) or not observations_raw:
        raise PhotorealAnimatedReviewPlanError("held-out reference catalog has no observations")

    source_count = value.get("held_out_source_count")
    observation_count = value.get("held_out_observation_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count != len(sources_raw):
        raise PhotorealAnimatedReviewPlanError("held-out reference source count mismatch")
    if isinstance(observation_count, bool) or not isinstance(observation_count, int) or observation_count != len(observations_raw):
        raise PhotorealAnimatedReviewPlanError("held-out reference observation count mismatch")

    sources: dict[str, dict[str, Any]] = {}
    for raw in sources_raw:
        if not isinstance(raw, Mapping) or set(raw) != REFERENCE_SOURCE_FIELDS:
            raise PhotorealAnimatedReviewPlanError("held-out reference source fields must match v1 exactly")
        source_key = _text(raw.get("source_key"), label="held-out source key")
        if source_key in sources:
            raise PhotorealAnimatedReviewPlanError("held-out reference catalog repeats source key")
        kind = raw.get("kind")
        if kind not in {"video", "image"}:
            raise PhotorealAnimatedReviewPlanError("held-out source kind is invalid")
        size_bytes = raw.get("size_bytes")
        if isinstance(size_bytes, bool) or not isinstance(size_bytes, int) or size_bytes < 1:
            raise PhotorealAnimatedReviewPlanError("held-out source size is invalid")
        sources[source_key] = {
            "source_key": source_key,
            "group_id": _text(raw.get("group_id"), label="held-out source group"),
            "kind": kind,
            "resolved_path": _text(raw.get("resolved_path"), label="held-out source path", maximum=32768),
            "size_bytes": size_bytes,
            "sha256": _sha(raw.get("sha256"), label="held-out source SHA-256"),
            "width": raw.get("width"),
            "height": raw.get("height"),
            "projection": _text(raw.get("projection"), label="held-out source projection", maximum=128),
            "stereo_layout": _text(raw.get("stereo_layout"), label="held-out stereo layout", maximum=128),
        }

    observations: dict[str, dict[str, Any]] = {}
    for raw in observations_raw:
        if not isinstance(raw, Mapping) or set(raw) != REFERENCE_OBSERVATION_FIELDS:
            raise PhotorealAnimatedReviewPlanError("held-out observation fields must match v1 exactly")
        observation_id = _sha(raw.get("observation_id"), label="held-out observation id")
        if observation_id in observations:
            raise PhotorealAnimatedReviewPlanError("held-out reference catalog repeats observation id")
        source_key = _text(raw.get("source_key"), label="held-out observation source key")
        source = sources.get(source_key)
        if source is None:
            raise PhotorealAnimatedReviewPlanError("held-out observation references unknown source")
        group_id = _text(raw.get("group_id"), label="held-out observation group")
        if group_id != source["group_id"]:
            raise PhotorealAnimatedReviewPlanError("held-out observation group/source binding mismatch")
        eye = raw.get("eye")
        if eye not in {"mono", "left", "right"}:
            raise PhotorealAnimatedReviewPlanError("held-out observation eye is invalid")
        coverage = raw.get("coverage")
        if not isinstance(coverage, list) or any(not isinstance(item, str) for item in coverage):
            raise PhotorealAnimatedReviewPlanError("held-out observation coverage is invalid")
        observations[observation_id] = {
            "observation_id": observation_id,
            "source_key": source_key,
            "group_id": group_id,
            "frame_sha256": _sha(raw.get("frame_sha256"), label="held-out observation frame SHA-256"),
            "timestamp_seconds": raw.get("timestamp_seconds"),
            "eye": eye,
            "view_bin": _text(raw.get("view_bin"), label="held-out observation view bin", maximum=64),
            "coverage": list(coverage),
        }
    return sources, observations


def _animation_artifact_map(receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in receipt["animation_artifacts"]:
        relative = _relative_path(raw.get("relative_path"), label="animation artifact relative path")
        if relative in result:
            raise PhotorealAnimatedReviewPlanError("animation execution receipt repeats artifact path")
        result[relative] = dict(raw)
    return result


def build_animated_review_plan(
    animation_execution_receipt: Mapping[str, Any],
    reference_catalog: Mapping[str, Any],
    selection_input: Mapping[str, Any],
    *,
    animation_output_root: str | Path,
) -> dict[str, Any]:
    try:
        execution = validate_animation_execution_receipt(animation_execution_receipt)
    except PhotorealAnimationExecutionReceiptError as exc:
        raise PhotorealAnimatedReviewPlanError(str(exc)) from exc
    sources, observations = _validate_reference_catalog(reference_catalog)

    if not (
        execution["performer_id"] == reference_catalog.get("performer_id")
        and execution["selected_epoch_id"] == reference_catalog.get("selected_epoch_id")
        and execution["teacher_input_sha256"] == reference_catalog.get("teacher_input_sha256")
    ):
        raise PhotorealAnimatedReviewPlanError("animation execution and held-out catalog lineage do not match")

    if set(selection_input) != SELECTION_INPUT_FIELDS:
        raise PhotorealAnimatedReviewPlanError("animated review selection input fields must match v1 exactly")
    if selection_input.get("format") != SELECTION_INPUT_FORMAT:
        raise PhotorealAnimatedReviewPlanError("animated review selection input format mismatch")
    _numeric_v1(selection_input.get("version"), label="animated review selection input")
    reviewer = _text(selection_input.get("reviewer"), label="animated review reviewer", maximum=256)
    if selection_input.get("operator_supplied") is not True:
        raise PhotorealAnimatedReviewPlanError("animated review selection must be operator supplied")
    selections_raw = selection_input.get("selections")
    if not isinstance(selections_raw, list) or len(selections_raw) != len(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealAnimatedReviewPlanError("animated review selection must cover every motion-review dimension exactly")

    animation_root = Path(animation_output_root).expanduser().resolve()
    if not animation_root.is_dir():
        raise PhotorealAnimatedReviewPlanError(f"animation output root not found: {animation_root}")
    artifact_map = _animation_artifact_map(execution)
    selected: dict[str, dict[str, Any]] = {}
    for raw in selections_raw:
        if not isinstance(raw, Mapping) or set(raw) != SELECTION_FIELDS:
            raise PhotorealAnimatedReviewPlanError("animated review selection fields must match v1 exactly")
        dimension = _text(raw.get("dimension"), label="motion-review dimension", maximum=80)
        if dimension not in MOTION_REVIEW_DIMENSIONS:
            raise PhotorealAnimatedReviewPlanError(f"unsupported motion-review dimension: {dimension}")
        if dimension in selected:
            raise PhotorealAnimatedReviewPlanError("animated review selection repeats motion-review dimension")
        relative = _relative_path(
            raw.get("animation_artifact_relative_path"), label="selected animation artifact relative path"
        )
        artifact = artifact_map.get(relative)
        if artifact is None:
            raise PhotorealAnimatedReviewPlanError("selected animation artifact is outside execution receipt")
        _, artifact_path = _safe_child(
            animation_root,
            relative,
            label="selected animation artifact relative path",
        )
        if not artifact_path.is_file():
            raise PhotorealAnimatedReviewPlanError(f"selected animation artifact is missing: {relative}")
        size = artifact.get("size_bytes")
        if isinstance(size, bool) or not isinstance(size, int) or artifact_path.stat().st_size != size:
            raise PhotorealAnimatedReviewPlanError(f"selected animation artifact size drifted: {relative}")
        observed_artifact_sha = _hash_file(artifact_path)
        if observed_artifact_sha != _sha(artifact.get("sha256"), label="selected animation artifact SHA-256"):
            raise PhotorealAnimatedReviewPlanError(f"selected animation artifact bytes drifted: {relative}")

        observation_id = _sha(raw.get("reference_observation_id"), label="selected held-out observation id")
        observation = observations.get(observation_id)
        if observation is None:
            raise PhotorealAnimatedReviewPlanError("selected held-out observation is outside reference catalog")
        source = sources[observation["source_key"]]
        if source["kind"] != "video":
            raise PhotorealAnimatedReviewPlanError("animated review evidence must come from held-out video")
        timestamp = _timestamp(
            observation.get("timestamp_seconds"), label="selected held-out motion observation"
        )
        before = _finite_window(raw.get("window_before_seconds"), label="window_before_seconds")
        after = _finite_window(raw.get("window_after_seconds"), label="window_after_seconds")
        start = round(max(0.0, timestamp - before), 6)
        end = round(timestamp + after, 6)
        if end <= start:
            raise PhotorealAnimatedReviewPlanError("animated review reference window is empty")

        selected[dimension] = {
            "dimension": dimension,
            "animation_artifact_kind": _text(artifact.get("kind"), label="animation artifact kind", maximum=64),
            "animation_artifact_relative_path": relative,
            "animation_artifact_size_bytes": size,
            "animation_artifact_sha256": observed_artifact_sha,
            "reference_observation_id": observation_id,
            "reference_source_key": source["source_key"],
            "reference_source_group_id": source["group_id"],
            "reference_source_resolved_path": source["resolved_path"],
            "reference_source_sha256": source["sha256"],
            "reference_source_projection": source["projection"],
            "reference_source_stereo_layout": source["stereo_layout"],
            "reference_timestamp_seconds": timestamp,
            "reference_eye": observation["eye"],
            "reference_view_bin": observation["view_bin"],
            "reference_frame_sha256": observation["frame_sha256"],
            "window_before_seconds": before,
            "window_after_seconds": after,
            "window_start_seconds": start,
            "window_end_seconds": end,
            "reference_motion_bytes_materialized": False,
        }

    if set(selected) != set(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealAnimatedReviewPlanError("animated review selection must cover every motion-review dimension exactly")

    ordered = [selected[dimension] for dimension in MOTION_REVIEW_DIMENSIONS]
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": execution["performer_id"],
        "selected_epoch_id": execution["selected_epoch_id"],
        "teacher_input_sha256": execution["teacher_input_sha256"],
        "teacher_manifest_sha256": execution["teacher_manifest_sha256"],
        "static_teacher_review_sha256": execution["static_teacher_review_sha256"],
        "animation_plan_sha256": execution["animation_plan_sha256"],
        "animation_execution_receipt_sha256": execution["animation_execution_receipt_sha256"],
        "held_out_reference_catalog_sha256": _sha(
            reference_catalog.get("held_out_reference_catalog_sha256"),
            label="held-out reference catalog SHA-256",
        ),
        "reviewer": reviewer,
        "operator_supplied": True,
        "motion_review_dimensions": list(MOTION_REVIEW_DIMENSIONS),
        "selection_count": len(ordered),
        "selections": ordered,
        "animation_artifact_bytes_reverified": True,
        "held_out_evaluation_only": True,
        "held_out_motion_reference_selection_complete": True,
        "motion_reference_materialization_required": True,
        "reference_motion_bytes_materialized": False,
        "human_animated_visual_acceptance_required": True,
        "animated_teacher_acceptance_authority": False,
        "p3_device_distillation_authorized": False,
        "source_paths_build_private": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    result["animated_review_plan_sha256"] = _digest_without(result, "animated_review_plan_sha256")
    return result


def build_animated_review_plan_files(
    animation_execution_receipt_path: str | Path,
    reference_catalog_path: str | Path,
    selection_input_path: str | Path,
    animation_output_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    execution = _read_json(animation_execution_receipt_path, label="animation execution receipt")
    catalog = _read_json(reference_catalog_path, label="held-out reference catalog")
    selections = _read_json(selection_input_path, label="animated review selection input")
    result = build_animated_review_plan(
        execution,
        catalog,
        selections,
        animation_output_root=animation_output_root,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealAnimatedReviewPlanError(f"animated review plan already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result
