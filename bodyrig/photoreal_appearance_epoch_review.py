from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

PLAN_FORMAT = "bodyrig-photoreal-appearance-epoch-plan"
PLAN_VERSION = 1
REVIEW_FORMAT = "bodyrig-photoreal-appearance-epoch-review"
REVIEW_VERSION = 1
FORMAT = "bodyrig-photoreal-appearance-epoch-selection"
VERSION = 1


class PhotorealAppearanceEpochReviewError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAppearanceEpochReviewError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAppearanceEpochReviewError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAppearanceEpochReviewError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum:
        raise PhotorealAppearanceEpochReviewError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAppearanceEpochReviewError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealAppearanceEpochReviewError(f"{label} is invalid")
    return result


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def apply_appearance_epoch_review(
    plan: Mapping[str, Any],
    review: Mapping[str, Any],
) -> dict[str, Any]:
    plan_version = plan.get("version")
    if (
        plan.get("format") != PLAN_FORMAT
        or isinstance(plan_version, bool)
        or not isinstance(plan_version, (int, float))
        or plan_version != PLAN_VERSION
    ):
        raise PhotorealAppearanceEpochReviewError("appearance epoch plan format/version mismatch")
    plan_sha = _sha(
        plan.get("appearance_epoch_plan_sha256"),
        label="appearance epoch plan SHA-256",
    )
    plan_core = dict(plan)
    plan_core.pop("appearance_epoch_plan_sha256", None)
    if _digest(plan_core) != plan_sha:
        raise PhotorealAppearanceEpochReviewError("appearance epoch plan digest mismatch")
    if plan.get("human_epoch_review_required") is not True:
        raise PhotorealAppearanceEpochReviewError("appearance epoch plan does not require human review")
    if plan.get("human_epoch_review_complete") is not False:
        raise PhotorealAppearanceEpochReviewError("appearance epoch plan already claims review completion")
    if plan.get("teacher_input_authorized") is not False or plan.get("teacher_training_authorized") is not False:
        raise PhotorealAppearanceEpochReviewError("appearance epoch plan crossed teacher authority before review")
    if plan.get("photoreal_acceptance_authority") is not False:
        raise PhotorealAppearanceEpochReviewError("appearance epoch plan crossed photoreal authority")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealAppearanceEpochReviewError("appearance epoch plan authority boundary is invalid")
    if plan.get("production_activation") is not False:
        raise PhotorealAppearanceEpochReviewError("appearance epoch plan crossed production authority")

    expected_review_fields = {
        "format",
        "version",
        "performer_id",
        "appearance_epoch_plan_sha256",
        "selected_epoch_id",
        "selected_source_group_ids",
        "human_review_complete",
        "human_approved",
        "reviewed_by",
        "review_notes",
        "production_activation",
    }
    if set(review) != expected_review_fields:
        raise PhotorealAppearanceEpochReviewError("appearance epoch review fields must match v1 exactly")
    version = review.get("version")
    if (
        review.get("format") != REVIEW_FORMAT
        or isinstance(version, bool)
        or not isinstance(version, (int, float))
        or version != REVIEW_VERSION
    ):
        raise PhotorealAppearanceEpochReviewError("appearance epoch review format/version mismatch")
    performer_id = _text(plan.get("performer_id"), label="plan performer id", maximum=256)
    if _text(review.get("performer_id"), label="review performer id", maximum=256) != performer_id:
        raise PhotorealAppearanceEpochReviewError("appearance epoch review performer mismatch")
    if _sha(review.get("appearance_epoch_plan_sha256"), label="review plan SHA-256") != plan_sha:
        raise PhotorealAppearanceEpochReviewError("appearance epoch review targets different plan")
    if review.get("human_review_complete") is not True or review.get("human_approved") is not True:
        raise PhotorealAppearanceEpochReviewError("appearance epoch selection requires explicit completed human approval")
    if review.get("production_activation") is not False:
        raise PhotorealAppearanceEpochReviewError("appearance epoch review crossed production authority")

    selected_epoch_id = _text(review.get("selected_epoch_id"), label="selected epoch id", maximum=256)
    reviewed_by = _text(review.get("reviewed_by"), label="appearance epoch reviewer", maximum=256)
    notes_raw = review.get("review_notes")
    if not isinstance(notes_raw, str) or len(notes_raw) > 8192:
        raise PhotorealAppearanceEpochReviewError("appearance epoch review notes are invalid")
    selected_raw = review.get("selected_source_group_ids")
    if not isinstance(selected_raw, list) or not selected_raw:
        raise PhotorealAppearanceEpochReviewError("appearance epoch review selected_source_group_ids are empty")
    selected = [_text(item, label="selected source group id") for item in selected_raw]
    if len(selected) != len(set(selected)):
        raise PhotorealAppearanceEpochReviewError("appearance epoch review repeats selected source groups")

    groups_raw = plan.get("eligible_source_groups")
    if not isinstance(groups_raw, list) or not groups_raw:
        raise PhotorealAppearanceEpochReviewError("appearance epoch plan contains no reviewable source groups")
    groups: dict[str, Mapping[str, Any]] = {}
    for raw in groups_raw:
        if not isinstance(raw, Mapping):
            raise PhotorealAppearanceEpochReviewError("appearance epoch plan contains invalid source group")
        group_id = _text(raw.get("group_id"), label="appearance epoch source group id")
        if group_id in groups:
            raise PhotorealAppearanceEpochReviewError("appearance epoch plan repeats source group")
        groups[group_id] = raw
    unknown = sorted(set(selected) - set(groups))
    if unknown:
        raise PhotorealAppearanceEpochReviewError(
            f"appearance epoch review selects unknown source groups ({len(unknown)})"
        )

    selected_groups = [groups[group_id] for group_id in selected]
    split_counts = {
        "train": sum(1 for item in selected_groups if item.get("split") == "train"),
        "evaluation": sum(1 for item in selected_groups if item.get("split") == "evaluation"),
    }
    if split_counts["train"] < 1 or split_counts["evaluation"] < 1:
        raise PhotorealAppearanceEpochReviewError(
            "approved appearance epoch must contain both train and held-out evaluation source groups"
        )

    performer_name_raw = plan.get("performer_name")
    if performer_name_raw is None:
        performer_name = ""
    elif isinstance(performer_name_raw, str):
        performer_name = performer_name_raw
    else:
        raise PhotorealAppearanceEpochReviewError("plan performer name is invalid")

    selected_sorted = sorted(selected)
    review_core = {
        "format": REVIEW_FORMAT,
        "version": REVIEW_VERSION,
        "performer_id": performer_id,
        "appearance_epoch_plan_sha256": plan_sha,
        "selected_epoch_id": selected_epoch_id,
        "selected_source_group_ids": selected_sorted,
        "human_review_complete": True,
        "human_approved": True,
        "reviewed_by": reviewed_by,
        "review_notes": notes_raw,
        "production_activation": False,
    }
    review_sha = _digest(review_core)
    selection_core = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "performer_name": performer_name,
        "appearance_epoch_plan_sha256": plan_sha,
        "appearance_epoch_review_sha256": review_sha,
        "selected_epoch_id": selected_epoch_id,
        "selected_source_group_ids": selected_sorted,
        "selected_train_group_count": split_counts["train"],
        "selected_evaluation_group_count": split_counts["evaluation"],
        "human_epoch_review_required": True,
        "human_epoch_review_complete": True,
        "human_approved": True,
        "teacher_input_authorized": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    selection_core["appearance_epoch_selection_sha256"] = _digest(selection_core)
    return selection_core


def apply_appearance_epoch_review_files(
    plan_path: str | Path,
    review_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="appearance epoch plan")
    review = _read_json(review_path, label="appearance epoch human review")
    result = apply_appearance_epoch_review(plan, review)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealAppearanceEpochReviewError(f"appearance epoch selection already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
