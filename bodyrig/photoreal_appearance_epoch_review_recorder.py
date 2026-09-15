from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoreal_appearance_epoch_handoff import (
    PhotorealAppearanceEpochHandoffError,
    build_appearance_epoch_review_handoff,
)
from .photoreal_appearance_epoch_review import (
    PhotorealAppearanceEpochReviewError,
    apply_appearance_epoch_review,
)

PLAN_FORMAT = "bodyrig-photoreal-appearance-epoch-plan"
PLAN_VERSION = 1
HANDOFF_FORMAT = "bodyrig-photoreal-appearance-epoch-review-handoff"
HANDOFF_VERSION = 1
REVIEW_FORMAT = "bodyrig-photoreal-appearance-epoch-review"
REVIEW_VERSION = 1


class PhotorealAppearanceEpochReviewRecorderError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAppearanceEpochReviewRecorderError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAppearanceEpochReviewRecorderError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealAppearanceEpochReviewRecorderError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealAppearanceEpochReviewRecorderError(f"{label} is invalid")
    return result


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PhotorealAppearanceEpochReviewRecorderError(f"{label} is invalid")
    return value


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_digest(value: Mapping[str, Any], field: str, *, label: str) -> str:
    claimed = _sha(value.get(field), label=f"{label} SHA-256")
    core = dict(value)
    core.pop(field, None)
    if _digest(core) != claimed:
        raise PhotorealAppearanceEpochReviewRecorderError(f"{label} digest mismatch")
    return claimed


def _candidate_groups(handoff: Mapping[str, Any]) -> dict[str, str]:
    raw_groups = handoff.get("candidate_source_groups")
    if not isinstance(raw_groups, list) or not raw_groups:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff contains no candidate source groups")
    groups: dict[str, str] = {}
    train_count = 0
    evaluation_count = 0
    for raw in raw_groups:
        if not isinstance(raw, Mapping):
            raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff contains an invalid candidate source group")
        group_id = _text(raw.get("group_id"), label="candidate source group id")
        if group_id in groups:
            raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff repeats candidate source group")
        split = _text(raw.get("split"), label="candidate source group split", maximum=32)
        if split not in {"train", "evaluation"}:
            raise PhotorealAppearanceEpochReviewRecorderError(f"unsupported candidate source group split: {split}")
        groups[group_id] = split
        if split == "train":
            train_count += 1
        else:
            evaluation_count += 1

    if _positive_int(handoff.get("source_group_count"), label="handoff source group count") != len(groups):
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff source group count mismatch")
    if _positive_int(handoff.get("train_source_group_count"), label="handoff train source group count") != train_count:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff train source group count mismatch")
    if _positive_int(handoff.get("evaluation_source_group_count"), label="handoff evaluation source group count") != evaluation_count:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff evaluation source group count mismatch")
    if train_count < 1 or evaluation_count < 1:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff must expose train and evaluation candidates")
    return groups


def build_human_review_record(
    plan: Mapping[str, Any],
    handoff: Mapping[str, Any],
    *,
    selected_epoch_id: str,
    selected_source_group_ids: Sequence[str],
    reviewed_by: str,
    review_notes: str,
    approve_human_review: bool,
) -> dict[str, Any]:
    plan_version = plan.get("version")
    if plan.get("format") != PLAN_FORMAT or isinstance(plan_version, bool) or plan_version != PLAN_VERSION:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch plan format/version mismatch")
    handoff_version = handoff.get("version")
    if handoff.get("format") != HANDOFF_FORMAT or isinstance(handoff_version, bool) or handoff_version != HANDOFF_VERSION:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch review handoff format/version mismatch")

    plan_sha = _validate_digest(plan, "appearance_epoch_plan_sha256", label="appearance epoch plan")
    _validate_digest(handoff, "appearance_epoch_review_handoff_sha256", label="appearance epoch review handoff")

    performer_id = _text(plan.get("performer_id"), label="plan performer id", maximum=256)
    if _text(handoff.get("performer_id"), label="handoff performer id", maximum=256) != performer_id:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff performer mismatch")
    if _sha(handoff.get("appearance_epoch_plan_sha256"), label="handoff plan SHA-256") != plan_sha:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff targets a different plan")

    for field, label in (
        ("source_frame_index_model_set_sha256", "source frame-index model-set SHA-256"),
        ("identity_bank_sha256", "identity bank SHA-256"),
        ("identity_calibration_sha256", "identity calibration SHA-256"),
        ("evidence_sha256", "appearance epoch evidence SHA-256"),
    ):
        if _sha(handoff.get(field), label=f"handoff {label}") != _sha(plan.get(field), label=f"plan {label}"):
            raise PhotorealAppearanceEpochReviewRecorderError(f"appearance epoch handoff {label} mismatch")

    if handoff.get("human_review_complete") is not False or handoff.get("human_approved") is not False:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff already claims human review authority")
    if handoff.get("teacher_input_authorized") is not False or handoff.get("teacher_training_authorized") is not False:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff crossed teacher authority")
    if handoff.get("photoreal_acceptance_authority") is not False or handoff.get("production_activation") is not False:
        raise PhotorealAppearanceEpochReviewRecorderError("appearance epoch handoff crossed downstream authority")

    try:
        canonical_handoff, _ = build_appearance_epoch_review_handoff(plan)
    except PhotorealAppearanceEpochHandoffError as exc:
        raise PhotorealAppearanceEpochReviewRecorderError(
            f"appearance epoch plan cannot regenerate the canonical review handoff: {exc}"
        ) from exc
    if dict(handoff) != canonical_handoff:
        raise PhotorealAppearanceEpochReviewRecorderError(
            "appearance epoch review handoff is not canonical for the supplied plan"
        )

    if approve_human_review is not True:
        raise PhotorealAppearanceEpochReviewRecorderError("explicit --approve-human-review is required")

    epoch_id = _text(selected_epoch_id, label="selected epoch id", maximum=256)
    reviewer = _text(reviewed_by, label="reviewed by", maximum=256)
    if not isinstance(review_notes, str) or not review_notes.strip() or len(review_notes) > 8192:
        raise PhotorealAppearanceEpochReviewRecorderError("review notes must be non-empty and at most 8192 characters")

    selected = [_text(item, label="selected source group id") for item in selected_source_group_ids]
    if not selected:
        raise PhotorealAppearanceEpochReviewRecorderError("at least one source group must be selected")
    if len(selected) != len(set(selected)):
        raise PhotorealAppearanceEpochReviewRecorderError("selected source groups contain duplicates")

    groups = _candidate_groups(handoff)
    unknown = sorted(set(selected) - set(groups))
    if unknown:
        raise PhotorealAppearanceEpochReviewRecorderError(
            f"selected source groups are not present in the handoff ({len(unknown)})"
        )
    selected_splits = {groups[group_id] for group_id in selected}
    if selected_splits != {"train", "evaluation"}:
        raise PhotorealAppearanceEpochReviewRecorderError(
            "human review must explicitly select at least one train and one held-out evaluation source group"
        )

    review = {
        "format": REVIEW_FORMAT,
        "version": REVIEW_VERSION,
        "performer_id": performer_id,
        "appearance_epoch_plan_sha256": plan_sha,
        "selected_epoch_id": epoch_id,
        "selected_source_group_ids": sorted(selected),
        "human_review_complete": True,
        "human_approved": True,
        "reviewed_by": reviewer,
        "review_notes": review_notes.strip(),
        "production_activation": False,
    }

    try:
        selection = apply_appearance_epoch_review(plan, review)
    except PhotorealAppearanceEpochReviewError as exc:
        raise PhotorealAppearanceEpochReviewRecorderError(
            f"generated human review is rejected by the existing appearance-epoch authority gate: {exc}"
        ) from exc
    if selection.get("teacher_input_authorized") is not True or selection.get("teacher_training_authorized") is not True:
        raise PhotorealAppearanceEpochReviewRecorderError("existing appearance-epoch authority gate did not authorize teacher input")
    if selection.get("photoreal_acceptance_authority") is not False or selection.get("production_activation") is not False:
        raise PhotorealAppearanceEpochReviewRecorderError("existing appearance-epoch authority gate crossed downstream authority")
    return review


def build_human_review_record_file(
    plan_path: str | Path,
    handoff_path: str | Path,
    output_path: str | Path,
    *,
    selected_epoch_id: str,
    selected_source_group_ids: Sequence[str],
    reviewed_by: str,
    review_notes: str,
    approve_human_review: bool,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="appearance epoch plan")
    handoff = _read_json(handoff_path, label="appearance epoch review handoff")
    review = build_human_review_record(
        plan,
        handoff,
        selected_epoch_id=selected_epoch_id,
        selected_source_group_ids=selected_source_group_ids,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
        approve_human_review=approve_human_review,
    )
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(review, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise PhotorealAppearanceEpochReviewRecorderError(f"human review record already exists: {output}") from exc
    except OSError as exc:
        raise PhotorealAppearanceEpochReviewRecorderError(f"failed to persist human review record: {output}") from exc
    return review
