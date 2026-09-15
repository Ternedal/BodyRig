from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .photoreal_animated_review_plan import MOTION_REVIEW_DIMENSIONS
from .photoreal_animation_execution_receipt import (
    PhotorealAnimationExecutionReceiptError,
    validate_animation_execution_receipt,
)
from .photoreal_motion_reference_materialization_authority import WINDOW_FIELDS
from .photoreal_motion_reference_receipt_authority import (
    PhotorealMotionReferenceReceiptAuthorityError,
    validate_motion_materialization_receipt_strict,
)
from .photoreal_motion_reference_materializer import PLAN_FIELDS, SELECTION_FIELDS

FORMAT = "bodyrig-photoreal-animated-teacher-human-review"
VERSION = 1
INPUT_FORMAT = "bodyrig-photoreal-animated-teacher-human-review-input"
CHECKS = {
    "temporal_stability",
    "identity_stable_across_motion",
    "appearance_stable_across_motion",
    "geometry_stable_no_collapse",
    "no_visible_texture_swimming_or_flicker",
    "motion_control_visually_coherent",
}
INPUT_FIELDS = {"format", "version", "reviewer", "operator_supplied", "dimension_reviews", "checklist", "overall_decision", "quality_note"}
DIMENSION_REVIEW_FIELDS = {"dimension", "outcome"}


class PhotorealAnimatedTeacherReviewError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAnimatedTeacherReviewError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAnimatedTeacherReviewError(f"{label} must be a JSON object")
    return value


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimatedTeacherReviewError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealAnimatedTeacherReviewError(f"{label} is invalid")
    return clean


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimatedTeacherReviewError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum or "\n" in clean or "\r" in clean:
        raise PhotorealAnimatedTeacherReviewError(f"{label} is invalid")
    return clean


def _v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) or value != VERSION:
        raise PhotorealAnimatedTeacherReviewError(f"{label} version must be numeric v1")


def _digest_without(value: Mapping[str, Any], key: str) -> str:
    payload = {name: item for name, item in value.items() if name != key}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
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
        raise PhotorealAnimatedTeacherReviewError(f"{label} escapes its root")
    return clean


def _safe_child(root: Path, relative: Any, *, label: str) -> tuple[str, Path]:
    clean = _relative_path(relative, label=label)
    target = (root / Path(clean)).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise PhotorealAnimatedTeacherReviewError(f"{label} escapes its root") from exc
    return clean, target


def _window_id(*, source_key: str, eye: str, start: float, end: float) -> str:
    payload = {"source_key": source_key, "eye": eye, "window_start_seconds": start, "window_end_seconds": end}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _validate_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != PLAN_FIELDS:
        raise PhotorealAnimatedTeacherReviewError("animated review plan fields must match v1 exactly")
    if value.get("format") != "bodyrig-photoreal-animated-review-plan":
        raise PhotorealAnimatedTeacherReviewError("animated review plan format mismatch")
    _v1(value.get("version"), label="animated review plan")
    declared = _sha(value.get("animated_review_plan_sha256"), label="animated review plan SHA-256")
    if declared != _digest_without(value, "animated_review_plan_sha256"):
        raise PhotorealAnimatedTeacherReviewError("animated review plan SHA-256 does not match content")
    for key in (
        "teacher_input_sha256", "teacher_manifest_sha256", "static_teacher_review_sha256",
        "animation_plan_sha256", "animation_execution_receipt_sha256", "held_out_reference_catalog_sha256",
    ):
        _sha(value.get(key), label=key)
    if value.get("operator_supplied") is not True:
        raise PhotorealAnimatedTeacherReviewError("animated review plan is not operator supplied")
    if value.get("motion_review_dimensions") != list(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealAnimatedTeacherReviewError("animated review plan dimension universe is not canonical")
    selections = value.get("selections")
    count = value.get("selection_count")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealAnimatedTeacherReviewError("animated review plan selection_count is invalid")
    if not isinstance(selections, list) or len(selections) != count:
        raise PhotorealAnimatedTeacherReviewError("animated review plan selections do not match count")
    dimensions: list[str] = []
    for raw in selections:
        if not isinstance(raw, Mapping) or set(raw) != SELECTION_FIELDS:
            raise PhotorealAnimatedTeacherReviewError("animated review selection fields must match v1 exactly")
        dimension = _text(raw.get("dimension"), label="motion-review dimension", maximum=80)
        dimensions.append(dimension)
        _sha(raw.get("animation_artifact_sha256"), label="selected animation artifact SHA-256")
        _sha(raw.get("reference_observation_id"), label="reference observation id")
        _sha(raw.get("reference_source_sha256"), label="reference source SHA-256")
        _sha(raw.get("reference_frame_sha256"), label="reference frame SHA-256")
        if raw.get("reference_motion_bytes_materialized") is not False:
            raise PhotorealAnimatedTeacherReviewError("animated review plan already claims materialized reference motion")
    if dimensions != list(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealAnimatedTeacherReviewError("animated review selections are not in canonical dimension order")
    if value.get("animation_artifact_bytes_reverified") is not True or value.get("held_out_evaluation_only") is not True:
        raise PhotorealAnimatedTeacherReviewError("animated review plan evidence authority is incomplete")
    if value.get("held_out_motion_reference_selection_complete") is not True:
        raise PhotorealAnimatedTeacherReviewError("animated review plan held-out selection is incomplete")
    if value.get("motion_reference_materialization_required") is not True or value.get("reference_motion_bytes_materialized") is not False:
        raise PhotorealAnimatedTeacherReviewError("animated review plan materialization phase boundary is invalid")
    if value.get("human_animated_visual_acceptance_required") is not True:
        raise PhotorealAnimatedTeacherReviewError("animated review plan removed human acceptance")
    if value.get("animated_teacher_acceptance_authority") is not False or value.get("p3_device_distillation_authorized") is not False:
        raise PhotorealAnimatedTeacherReviewError("animated review plan crossed downstream authority")
    if value.get("source_paths_build_private") is not True or value.get("build_only") is not True or value.get("runtime_dependency") is not False or value.get("production_activation") is not False:
        raise PhotorealAnimatedTeacherReviewError("animated review plan build/runtime boundary is invalid")
    return dict(value)


def _human_input(value: Mapping[str, Any]) -> tuple[str, dict[str, str], dict[str, str], str, str]:
    if set(value) != INPUT_FIELDS or value.get("format") != INPUT_FORMAT:
        raise PhotorealAnimatedTeacherReviewError("animated human review input fields/format mismatch")
    _v1(value.get("version"), label="animated human review input")
    reviewer = _text(value.get("reviewer"), label="reviewer", maximum=256)
    if value.get("operator_supplied") is not True:
        raise PhotorealAnimatedTeacherReviewError("animated human review must be operator supplied")
    reviews = value.get("dimension_reviews")
    if not isinstance(reviews, list) or len(reviews) != len(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealAnimatedTeacherReviewError("animated human review must cover every motion dimension exactly")
    outcomes: dict[str, str] = {}
    for raw in reviews:
        if not isinstance(raw, Mapping) or set(raw) != DIMENSION_REVIEW_FIELDS:
            raise PhotorealAnimatedTeacherReviewError("animated dimension review fields must match v1 exactly")
        dimension = _text(raw.get("dimension"), label="animated review dimension", maximum=80)
        if dimension not in MOTION_REVIEW_DIMENSIONS or dimension in outcomes:
            raise PhotorealAnimatedTeacherReviewError("animated human review dimension is unsupported or repeated")
        outcome = raw.get("outcome")
        if outcome not in {"pass", "fail"}:
            raise PhotorealAnimatedTeacherReviewError("animated dimension review outcome is invalid")
        outcomes[dimension] = str(outcome)
    if set(outcomes) != set(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealAnimatedTeacherReviewError("animated human review dimension universe is incomplete")
    checklist = value.get("checklist")
    if not isinstance(checklist, Mapping) or set(checklist) != CHECKS:
        raise PhotorealAnimatedTeacherReviewError("animated human review checklist is not canonical")
    check_outcomes: dict[str, str] = {}
    for key in sorted(CHECKS):
        outcome = checklist.get(key)
        if outcome not in {"pass", "fail"}:
            raise PhotorealAnimatedTeacherReviewError(f"animated human review checklist outcome is invalid: {key}")
        check_outcomes[key] = str(outcome)
    overall = value.get("overall_decision")
    if overall not in {"pass", "fail"}:
        raise PhotorealAnimatedTeacherReviewError("animated human review overall decision is invalid")
    note = _text(value.get("quality_note"), label="quality note", maximum=4000)
    expected_pass = all(item == "pass" for item in outcomes.values()) and all(item == "pass" for item in check_outcomes.values())
    if (overall == "pass") != expected_pass:
        raise PhotorealAnimatedTeacherReviewError("animated human review overall decision contradicts detailed outcomes")
    return reviewer, outcomes, check_outcomes, str(overall), note


def finalize_animated_teacher_review(
    animation_execution_receipt: Mapping[str, Any],
    animated_review_plan: Mapping[str, Any],
    motion_materialization_receipt: Mapping[str, Any],
    human_review_input: Mapping[str, Any],
    *,
    animation_output_root: str | Path,
    motion_output_root: str | Path,
) -> dict[str, Any]:
    try:
        execution = validate_animation_execution_receipt(animation_execution_receipt)
    except PhotorealAnimationExecutionReceiptError as exc:
        raise PhotorealAnimatedTeacherReviewError(str(exc)) from exc
    plan = _validate_plan(animated_review_plan)
    try:
        materialization = validate_motion_materialization_receipt_strict(motion_materialization_receipt)
    except PhotorealMotionReferenceReceiptAuthorityError as exc:
        raise PhotorealAnimatedTeacherReviewError(str(exc)) from exc
    reviewer, outcomes, checklist, overall, note = _human_input(human_review_input)

    if not (
        execution["performer_id"] == plan["performer_id"] == materialization["performer_id"]
        and execution["selected_epoch_id"] == plan["selected_epoch_id"] == materialization["selected_epoch_id"]
        and execution["teacher_input_sha256"] == plan["teacher_input_sha256"] == materialization["teacher_input_sha256"]
    ):
        raise PhotorealAnimatedTeacherReviewError("animated review performer/epoch/teacher lineage mismatch")
    if execution["teacher_manifest_sha256"] != plan["teacher_manifest_sha256"]:
        raise PhotorealAnimatedTeacherReviewError("animated review teacher manifest lineage mismatch")
    if execution["static_teacher_review_sha256"] != plan["static_teacher_review_sha256"]:
        raise PhotorealAnimatedTeacherReviewError("animated review static-teacher lineage mismatch")
    if execution["animation_plan_sha256"] != plan["animation_plan_sha256"]:
        raise PhotorealAnimatedTeacherReviewError("animated review animation-plan lineage mismatch")
    if execution["animation_execution_receipt_sha256"] != plan["animation_execution_receipt_sha256"]:
        raise PhotorealAnimatedTeacherReviewError("animated review execution-receipt lineage mismatch")
    if materialization["animation_execution_receipt_sha256"] != execution["animation_execution_receipt_sha256"]:
        raise PhotorealAnimatedTeacherReviewError("motion materialization targets different animation execution")
    if materialization["animated_review_plan_sha256"] != plan["animated_review_plan_sha256"]:
        raise PhotorealAnimatedTeacherReviewError("motion materialization targets different animated review plan")
    if materialization["held_out_reference_catalog_sha256"] != plan["held_out_reference_catalog_sha256"]:
        raise PhotorealAnimatedTeacherReviewError("motion materialization targets different held-out catalog")

    animation_root = Path(animation_output_root).expanduser().resolve()
    motion_root = Path(motion_output_root).expanduser().resolve()
    if not animation_root.is_dir() or not motion_root.is_dir():
        raise PhotorealAnimatedTeacherReviewError("animated review output root is missing")

    execution_artifacts = {item["relative_path"]: item for item in execution["animation_artifacts"]}
    windows = {item["window_id"]: item for item in materialization["materialized_windows"]}
    verified_motion_windows: set[str] = set()
    evidence: list[dict[str, Any]] = []

    for selection in plan["selections"]:
        dimension = selection["dimension"]
        relative = _relative_path(selection["animation_artifact_relative_path"], label="selected animation artifact path")
        artifact = execution_artifacts.get(relative)
        if artifact is None:
            raise PhotorealAnimatedTeacherReviewError("selected animation artifact is absent from execution receipt")
        selected_sha = _sha(selection["animation_artifact_sha256"], label="selected animation artifact SHA-256")
        if artifact["sha256"] != selected_sha or artifact["size_bytes"] != selection["animation_artifact_size_bytes"] or artifact["kind"] != selection["animation_artifact_kind"]:
            raise PhotorealAnimatedTeacherReviewError("selected animation artifact differs from execution receipt")
        _, artifact_path = _safe_child(animation_root, relative, label="selected animation artifact path")
        if not artifact_path.is_file() or artifact_path.stat().st_size != artifact["size_bytes"] or _hash_file(artifact_path) != selected_sha:
            raise PhotorealAnimatedTeacherReviewError("selected animation artifact bytes drifted before human review")

        start = round(float(selection["window_start_seconds"]), 6)
        end = round(float(selection["window_end_seconds"]), 6)
        window_id = _window_id(
            source_key=selection["reference_source_key"],
            eye=selection["reference_eye"],
            start=start,
            end=end,
        )
        window = windows.get(window_id)
        if window is None or dimension not in window["dimensions"]:
            raise PhotorealAnimatedTeacherReviewError("materialized motion window does not authorize review dimension")
        anchor = next((item for item in window["anchors"] if item["observation_id"] == selection["reference_observation_id"]), None)
        if anchor is None or dimension not in anchor["dimensions"]:
            raise PhotorealAnimatedTeacherReviewError("materialized motion anchor does not authorize review dimension")
        if anchor["expected_frame_sha256"] != selection["reference_frame_sha256"] or anchor["timestamp_seconds"] != selection["reference_timestamp_seconds"]:
            raise PhotorealAnimatedTeacherReviewError("materialized motion anchor differs from review plan")

        if window_id not in verified_motion_windows:
            for frame in window["frames"]:
                frame_relative, frame_path = _safe_child(motion_root, frame["png_relative_path"], label="materialized motion PNG path")
                if frame_relative != frame["png_relative_path"]:
                    raise PhotorealAnimatedTeacherReviewError("materialized motion PNG path is not canonical")
                if not frame_path.is_file() or frame_path.stat().st_size != frame["png_size_bytes"] or _hash_file(frame_path) != frame["png_sha256"]:
                    raise PhotorealAnimatedTeacherReviewError("materialized motion PNG bytes drifted before human review")
            verified_motion_windows.add(window_id)

        evidence.append({
            "dimension": dimension,
            "animation_artifact_relative_path": relative,
            "animation_artifact_sha256": selected_sha,
            "motion_window_id": window_id,
            "reference_observation_id": selection["reference_observation_id"],
            "reference_frame_sha256": selection["reference_frame_sha256"],
            "materialized_reference_frame_count": window["frame_count"],
            "human_outcome": outcomes[dimension],
        })

    passed = overall == "pass"
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
        "animated_review_plan_sha256": plan["animated_review_plan_sha256"],
        "motion_materialization_receipt_sha256": materialization["motion_materialization_receipt_sha256"],
        "reviewer": reviewer,
        "reviewed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "operator_supplied": True,
        "dimension_review_count": len(evidence),
        "dimension_reviews": evidence,
        "checklist": checklist,
        "quality_note": note,
        "animation_artifact_bytes_reverified_at_review": True,
        "motion_reference_bytes_reverified_at_review": True,
        "human_animated_review_complete": True,
        "human_animated_review_outcome": overall,
        "human_animated_review_pass": passed,
        "animated_teacher_photoreal_accepted": passed,
        "animated_teacher_acceptance_authority": passed,
        "p3_device_distillation_authorized": passed,
        "production_activation": False,
    }
    result["animated_teacher_review_sha256"] = _digest_without(result, "animated_teacher_review_sha256")
    return result


def finalize_animated_teacher_review_files(
    animation_execution_receipt_path: str | Path,
    animated_review_plan_path: str | Path,
    motion_materialization_receipt_path: str | Path,
    human_review_input_path: str | Path,
    animation_output_root: str | Path,
    motion_output_root: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    result = finalize_animated_teacher_review(
        _read_json(animation_execution_receipt_path, label="animation execution receipt"),
        _read_json(animated_review_plan_path, label="animated review plan"),
        _read_json(motion_materialization_receipt_path, label="motion materialization receipt"),
        _read_json(human_review_input_path, label="animated human review input"),
        animation_output_root=animation_output_root,
        motion_output_root=motion_output_root,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealAnimatedTeacherReviewError(f"animated teacher human review already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
