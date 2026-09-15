from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .photoreal_static_teacher_review import CHECKS, FORMAT, VERSION

TOP_FIELDS = {
    "format",
    "version",
    "performer_id",
    "selected_epoch_id",
    "teacher_input_sha256",
    "review_render_set_sha256",
    "review_mapping_sha256",
    "held_out_reference_catalog_sha256",
    "materialization_receipt_sha256",
    "reviewer",
    "reviewed_utc",
    "operator_supplied",
    "comparison_count",
    "comparisons",
    "checklist",
    "quality_note",
    "human_review_complete",
    "human_review_outcome",
    "human_review_pass",
    "static_teacher_photoreal_accepted",
    "photoreal_acceptance_authority",
    "p2_animation_work_authorized",
    "runtime_dependency",
    "production_activation",
    "static_teacher_review_sha256",
}
COMPARISON_FIELDS = {
    "coverage",
    "teacher_render_orbit_index",
    "teacher_render_relative_path",
    "teacher_render_sha256",
    "reference_observation_id",
    "reference_png_relative_path",
    "reference_png_sha256",
    "reference_frame_sha256",
    "human_outcome",
}


class PhotorealStaticTeacherReviewAuthorityError(ValueError):
    pass


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealStaticTeacherReviewAuthorityError(f"{label} is invalid")
    clean = value.strip().lower()
    if len(clean) != 64 or any(ch not in "0123456789abcdef" for ch in clean):
        raise PhotorealStaticTeacherReviewAuthorityError(f"{label} is invalid")
    return clean


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealStaticTeacherReviewAuthorityError(f"{label} is invalid")
    clean = value.strip()
    if not clean or len(value) > maximum:
        raise PhotorealStaticTeacherReviewAuthorityError(f"{label} is invalid")
    return value


def _digest(value: Mapping[str, Any]) -> str:
    payload = {key: item for key, item in value.items() if key != "static_teacher_review_sha256"}
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def validate_static_teacher_review(value: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != TOP_FIELDS:
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher review fields must match v1 exactly")
    version = value.get("version")
    if value.get("format") != FORMAT or isinstance(version, bool) or not isinstance(version, (int, float)):
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher review format/version mismatch")
    if not math.isfinite(float(version)) or version != VERSION:
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher review format/version mismatch")

    _text(value.get("performer_id"), label="review performer id", maximum=256)
    _text(value.get("selected_epoch_id"), label="review selected epoch id", maximum=256)
    for key in (
        "teacher_input_sha256",
        "review_render_set_sha256",
        "review_mapping_sha256",
        "held_out_reference_catalog_sha256",
        "materialization_receipt_sha256",
    ):
        _sha(value.get(key), label=key)
    _text(value.get("reviewer"), label="reviewer", maximum=256)
    reviewed_utc = _text(value.get("reviewed_utc"), label="reviewed_utc", maximum=64)
    try:
        parsed = datetime.fromisoformat(reviewed_utc.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PhotorealStaticTeacherReviewAuthorityError("reviewed_utc is invalid") from exc
    if parsed.tzinfo is None:
        raise PhotorealStaticTeacherReviewAuthorityError("reviewed_utc must be timezone-aware")
    if value.get("operator_supplied") is not True:
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher review is not operator supplied")

    comparisons = value.get("comparisons")
    count = value.get("comparison_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 1:
        raise PhotorealStaticTeacherReviewAuthorityError("comparison_count is invalid")
    if not isinstance(comparisons, list) or len(comparisons) != count:
        raise PhotorealStaticTeacherReviewAuthorityError("comparison_count does not match comparisons")
    coverage_seen: set[str] = set()
    comparison_outcomes: list[str] = []
    for raw in comparisons:
        if not isinstance(raw, Mapping) or set(raw) != COMPARISON_FIELDS:
            raise PhotorealStaticTeacherReviewAuthorityError("comparison fields must match v1 exactly")
        coverage = _text(raw.get("coverage"), label="comparison coverage", maximum=64)
        if coverage in coverage_seen:
            raise PhotorealStaticTeacherReviewAuthorityError("static teacher review repeats comparison coverage")
        coverage_seen.add(coverage)
        orbit = raw.get("teacher_render_orbit_index")
        if isinstance(orbit, bool) or not isinstance(orbit, int) or not 0 <= orbit < 50:
            raise PhotorealStaticTeacherReviewAuthorityError("comparison teacher orbit index is invalid")
        _text(raw.get("teacher_render_relative_path"), label="teacher render relative path")
        _sha(raw.get("teacher_render_sha256"), label="teacher render SHA-256")
        _sha(raw.get("reference_observation_id"), label="reference observation id")
        _text(raw.get("reference_png_relative_path"), label="reference PNG relative path")
        _sha(raw.get("reference_png_sha256"), label="reference PNG SHA-256")
        _sha(raw.get("reference_frame_sha256"), label="reference frame SHA-256")
        outcome = raw.get("human_outcome")
        if outcome not in {"pass", "fail"}:
            raise PhotorealStaticTeacherReviewAuthorityError("comparison human_outcome is invalid")
        comparison_outcomes.append(str(outcome))

    checklist = value.get("checklist")
    if not isinstance(checklist, Mapping) or set(checklist) != CHECKS:
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher review checklist is not canonical")
    checklist_outcomes: list[str] = []
    for key in sorted(CHECKS):
        outcome = checklist.get(key)
        if outcome not in {"pass", "fail"}:
            raise PhotorealStaticTeacherReviewAuthorityError(f"static teacher review checklist outcome is invalid: {key}")
        checklist_outcomes.append(str(outcome))
    _text(value.get("quality_note"), label="quality_note", maximum=4000)
    if value.get("human_review_complete") is not True:
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher human review is incomplete")
    outcome = value.get("human_review_outcome")
    if outcome not in {"pass", "fail"}:
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher human review outcome is invalid")
    expected_pass = all(item == "pass" for item in comparison_outcomes) and all(item == "pass" for item in checklist_outcomes)
    if (outcome == "pass") != expected_pass:
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher review outcome contradicts detailed evidence")
    for key in (
        "human_review_pass",
        "static_teacher_photoreal_accepted",
        "photoreal_acceptance_authority",
        "p2_animation_work_authorized",
    ):
        if value.get(key) is not expected_pass:
            raise PhotorealStaticTeacherReviewAuthorityError(f"static teacher review authority mismatch: {key}")
    if value.get("runtime_dependency") is not False or value.get("production_activation") is not False:
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher review crossed runtime/production authority")
    declared = _sha(value.get("static_teacher_review_sha256"), label="static teacher review SHA-256")
    if declared != _digest(value):
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher review SHA-256 does not match receipt content")
    return dict(value)


def read_static_teacher_review(path: str | Path) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealStaticTeacherReviewAuthorityError(f"static teacher review is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealStaticTeacherReviewAuthorityError("static teacher review must be a JSON object")
    return validate_static_teacher_review(value)


def require_p2_animation_authority(value: Mapping[str, Any]) -> dict[str, Any]:
    validated = validate_static_teacher_review(value)
    if validated["p2_animation_work_authorized"] is not True:
        raise PhotorealStaticTeacherReviewAuthorityError(
            "P2 animation work requires an exact human-passed Photoreal static teacher review"
        )
    return validated
