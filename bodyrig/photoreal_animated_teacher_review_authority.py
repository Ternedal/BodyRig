from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .photoreal_animated_review_plan import MOTION_REVIEW_DIMENSIONS
from .photoreal_animated_teacher_review import CHECKS, FORMAT, VERSION

TOP_FIELDS = {
    "format", "version", "performer_id", "selected_epoch_id", "teacher_input_sha256",
    "teacher_manifest_sha256", "static_teacher_review_sha256", "animation_plan_sha256",
    "animation_execution_receipt_sha256", "animated_review_plan_sha256",
    "motion_materialization_receipt_sha256", "reviewer", "reviewed_utc", "operator_supplied",
    "dimension_review_count", "dimension_reviews", "checklist", "quality_note",
    "animation_artifact_bytes_reverified_at_review", "motion_reference_bytes_reverified_at_review",
    "human_animated_review_complete", "human_animated_review_outcome", "human_animated_review_pass",
    "animated_teacher_photoreal_accepted", "animated_teacher_acceptance_authority",
    "p3_device_distillation_authorized", "production_activation", "animated_teacher_review_sha256",
}
DIMENSION_FIELDS = {
    "dimension", "animation_artifact_relative_path", "animation_artifact_sha256",
    "motion_window_id", "reference_observation_id", "reference_frame_sha256",
    "materialized_reference_frame_count", "human_outcome",
}


class PhotorealAnimatedTeacherReviewAuthorityError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimatedTeacherReviewAuthorityError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealAnimatedTeacherReviewAuthorityError(f"{label} is invalid")
    return clean


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAnimatedTeacherReviewAuthorityError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(clean) > maximum:
        raise PhotorealAnimatedTeacherReviewAuthorityError(f"{label} is invalid")
    return clean


def _digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "animated_teacher_review_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def validate_animated_teacher_review(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != TOP_FIELDS:
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != FORMAT or isinstance(version, bool) or not isinstance(version, (int, float)):
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review format/version mismatch")
    if not math.isfinite(float(version)) or version != VERSION:
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review format/version mismatch")
    _text(value.get("performer_id"), label="review performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="review epoch id", maximum=256)
    for key in (
        "teacher_input_sha256", "teacher_manifest_sha256", "static_teacher_review_sha256",
        "animation_plan_sha256", "animation_execution_receipt_sha256", "animated_review_plan_sha256",
        "motion_materialization_receipt_sha256",
    ):
        _sha(value.get(key), label=key)
    _text(value.get("reviewer"), label="reviewer", maximum=256)
    reviewed = _text(value.get("reviewed_utc"), label="reviewed_utc", maximum=64)
    try:
        parsed = datetime.fromisoformat(reviewed.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PhotorealAnimatedTeacherReviewAuthorityError("reviewed_utc is invalid") from exc
    if parsed.tzinfo is None:
        raise PhotorealAnimatedTeacherReviewAuthorityError("reviewed_utc must be timezone-aware")
    if value.get("operator_supplied") is not True:
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review is not operator supplied")

    reviews = value.get("dimension_reviews")
    count = value.get("dimension_review_count")
    if isinstance(count, bool) or not isinstance(count, int) or count != len(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review dimension count is invalid")
    if not isinstance(reviews, list) or len(reviews) != count:
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review dimension count does not match reviews")
    outcomes: dict[str, str] = {}
    for raw in reviews:
        if not isinstance(raw, Mapping) or set(raw) != DIMENSION_FIELDS:
            raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher dimension fields must match v1 exactly")
        dimension = _text(raw.get("dimension"), label="animated teacher review dimension", maximum=80)
        if dimension not in MOTION_REVIEW_DIMENSIONS or dimension in outcomes:
            raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review dimension is unsupported or repeated")
        _text(raw.get("animation_artifact_relative_path"), label="animation artifact path")
        _sha(raw.get("animation_artifact_sha256"), label="animation artifact SHA-256")
        _sha(raw.get("motion_window_id"), label="motion window id")
        _sha(raw.get("reference_observation_id"), label="reference observation id")
        _sha(raw.get("reference_frame_sha256"), label="reference frame SHA-256")
        frame_count = raw.get("materialized_reference_frame_count")
        if isinstance(frame_count, bool) or not isinstance(frame_count, int) or frame_count < 2:
            raise PhotorealAnimatedTeacherReviewAuthorityError("materialized reference frame count is invalid")
        outcome = raw.get("human_outcome")
        if outcome not in {"pass", "fail"}:
            raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review outcome is invalid")
        outcomes[dimension] = str(outcome)
    if set(outcomes) != set(MOTION_REVIEW_DIMENSIONS):
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review dimension universe is incomplete")

    checklist = value.get("checklist")
    if not isinstance(checklist, Mapping) or set(checklist) != CHECKS:
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review checklist is not canonical")
    checklist_outcomes: list[str] = []
    for key in sorted(CHECKS):
        outcome = checklist.get(key)
        if outcome not in {"pass", "fail"}:
            raise PhotorealAnimatedTeacherReviewAuthorityError(f"animated teacher checklist outcome is invalid: {key}")
        checklist_outcomes.append(str(outcome))
    _text(value.get("quality_note"), label="quality note", maximum=4000)
    if value.get("animation_artifact_bytes_reverified_at_review") is not True or value.get("motion_reference_bytes_reverified_at_review") is not True:
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review did not reverify exact review bytes")
    if value.get("human_animated_review_complete") is not True:
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher human review is incomplete")
    overall = value.get("human_animated_review_outcome")
    if overall not in {"pass", "fail"}:
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher human review outcome is invalid")
    expected_pass = all(item == "pass" for item in outcomes.values()) and all(item == "pass" for item in checklist_outcomes)
    if (overall == "pass") != expected_pass:
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review outcome contradicts detailed evidence")
    for key in (
        "human_animated_review_pass", "animated_teacher_photoreal_accepted",
        "animated_teacher_acceptance_authority", "p3_device_distillation_authorized",
    ):
        if value.get(key) is not expected_pass:
            raise PhotorealAnimatedTeacherReviewAuthorityError(f"animated teacher review authority mismatch: {key}")
    if value.get("production_activation") is not False:
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review crossed production authority")
    declared = _sha(value.get("animated_teacher_review_sha256"), label="animated teacher review SHA-256")
    if declared != _digest(value):
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review SHA-256 does not match content")
    return dict(value)


def require_p3_device_distillation_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_animated_teacher_review(value)
    if validated["p3_device_distillation_authorized"] is not True:
        raise PhotorealAnimatedTeacherReviewAuthorityError(
            "P3 device distillation requires an exact human-passed animated teacher review"
        )
    return validated


def read_animated_teacher_review(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAnimatedTeacherReviewAuthorityError(f"animated teacher review is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAnimatedTeacherReviewAuthorityError("animated teacher review must be a JSON object")
    return validate_animated_teacher_review(value)
