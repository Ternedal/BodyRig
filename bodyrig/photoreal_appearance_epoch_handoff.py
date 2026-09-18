from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

PLAN_FORMAT = "bodyrig-photoreal-appearance-epoch-plan"
PLAN_VERSION = 1
PLAN_STRATEGY = "human-review-required-v1"
REVIEW_FORMAT = "bodyrig-photoreal-appearance-epoch-review"
REVIEW_VERSION = 1
FORMAT = "bodyrig-photoreal-appearance-epoch-review-handoff"
VERSION = 1


class PhotorealAppearanceEpochHandoffError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAppearanceEpochHandoffError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAppearanceEpochHandoffError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAppearanceEpochHandoffError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum:
        raise PhotorealAppearanceEpochHandoffError(f"{label} is invalid")
    return result


def _optional_text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > maximum:
        raise PhotorealAppearanceEpochHandoffError(f"{label} is invalid")
    return value


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAppearanceEpochHandoffError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealAppearanceEpochHandoffError(f"{label} is invalid")
    return result


def _positive_int(value: Any, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PhotorealAppearanceEpochHandoffError(f"{label} is invalid")
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


def _string_list(value: Any, *, label: str, sha_values: bool = False) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PhotorealAppearanceEpochHandoffError(f"{label} is empty or invalid")
    result: list[str] = []
    for item in value:
        result.append(_sha(item, label=label) if sha_values else _text(item, label=label))
    if len(result) != len(set(result)):
        raise PhotorealAppearanceEpochHandoffError(f"{label} contains duplicates")
    return sorted(result)


def _validate_plan_digest(plan: Mapping[str, Any]) -> str:
    claimed = _sha(plan.get("appearance_epoch_plan_sha256"), label="appearance epoch plan SHA-256")
    core = dict(plan)
    core.pop("appearance_epoch_plan_sha256", None)
    actual = _digest(core)
    if actual != claimed:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan digest mismatch")
    return claimed


def build_appearance_epoch_review_handoff(
    plan: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    version = plan.get("version")
    if plan.get("format") != PLAN_FORMAT or isinstance(version, bool) or version != PLAN_VERSION:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan format/version mismatch")
    strategy = _text(plan.get("strategy"), label="appearance epoch strategy", maximum=128)
    if strategy != PLAN_STRATEGY:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan strategy is not the canonical human-review strategy")
    if plan.get("human_epoch_review_required") is not True:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan does not require human review")
    if plan.get("human_epoch_review_complete") is not False:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan already claims review completion")
    if plan.get("teacher_input_authorized") is not False or plan.get("teacher_training_authorized") is not False:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan crossed teacher authority before review")
    if plan.get("photoreal_acceptance_authority") is not False:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan crossed photoreal authority")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan build/runtime authority boundary is invalid")
    if plan.get("production_activation") is not False:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan crossed production authority")
    if plan.get("candidate_epochs") != [] or plan.get("selected_epoch_id") is not None:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan already contains an epoch selection")

    performer_id = _text(plan.get("performer_id"), label="performer id", maximum=256)
    performer_name = _optional_text(plan.get("performer_name"), label="performer name")
    plan_sha = _validate_plan_digest(plan)
    evidence_sha = _sha(plan.get("evidence_sha256"), label="appearance epoch evidence SHA-256")
    model_set_sha = _sha(
        plan.get("source_frame_index_model_set_sha256"), label="source frame-index model-set SHA-256"
    )
    identity_bank_sha = _sha(plan.get("identity_bank_sha256"), label="identity bank SHA-256")
    identity_calibration_sha = _sha(
        plan.get("identity_calibration_sha256"), label="identity calibration SHA-256"
    )

    groups_raw = plan.get("eligible_source_groups")
    if not isinstance(groups_raw, list) or not groups_raw:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch plan contains no reviewable source groups")

    candidates: list[dict[str, Any]] = []
    seen_group_ids: set[str] = set()
    train_group_count = 0
    evaluation_group_count = 0
    train_observations = 0
    evaluation_observations = 0
    for raw in groups_raw:
        if not isinstance(raw, Mapping):
            raise PhotorealAppearanceEpochHandoffError("appearance epoch plan contains an invalid source group")
        group_id = _text(raw.get("group_id"), label="source group id")
        if group_id in seen_group_ids:
            raise PhotorealAppearanceEpochHandoffError("appearance epoch plan repeats source group")
        seen_group_ids.add(group_id)
        split = _text(raw.get("split"), label="source group split", maximum=32)
        if split not in {"train", "evaluation"}:
            raise PhotorealAppearanceEpochHandoffError(f"unsupported source group split: {split}")
        source_keys = _string_list(raw.get("source_keys"), label="source group source key")
        frame_sha256s = _string_list(raw.get("frame_sha256s"), label="source group frame SHA-256", sha_values=True)
        view_bins = _string_list(raw.get("view_bins"), label="source group view bin")
        observation_count = _positive_int(
            raw.get("eligible_observation_count"), label="source group eligible observation count"
        )
        candidates.append(
            {
                "group_id": group_id,
                "split": split,
                "source_keys": source_keys,
                "frame_sha256s": frame_sha256s,
                "view_bins": view_bins,
                "eligible_observation_count": observation_count,
            }
        )
        if split == "train":
            train_group_count += 1
            train_observations += observation_count
        else:
            evaluation_group_count += 1
            evaluation_observations += observation_count

    if train_group_count < 1 or evaluation_group_count < 1:
        raise PhotorealAppearanceEpochHandoffError(
            "appearance epoch review requires both train and held-out evaluation source groups"
        )
    candidates.sort(key=lambda item: (str(item["split"]), str(item["group_id"])))

    source_group_count = _positive_int(plan.get("source_group_count"), label="source group count")
    eligible_count = _positive_int(plan.get("eligible_observation_count"), label="eligible observation count")
    eligible_train_count = _positive_int(
        plan.get("eligible_train_observation_count"), label="eligible train observation count"
    )
    eligible_evaluation_count = _positive_int(
        plan.get("eligible_evaluation_observation_count"), label="eligible evaluation observation count"
    )
    if source_group_count != len(candidates):
        raise PhotorealAppearanceEpochHandoffError("appearance epoch source group count mismatch")
    if eligible_count != train_observations + evaluation_observations:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch eligible observation count mismatch")
    if eligible_train_count != train_observations:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch train observation count mismatch")
    if eligible_evaluation_count != evaluation_observations:
        raise PhotorealAppearanceEpochHandoffError("appearance epoch evaluation observation count mismatch")

    review_template = {
        "format": REVIEW_FORMAT,
        "version": REVIEW_VERSION,
        "performer_id": performer_id,
        "appearance_epoch_plan_sha256": plan_sha,
        "selected_epoch_id": None,
        "selected_source_group_ids": [],
        "human_review_complete": False,
        "human_approved": False,
        "reviewed_by": "",
        "review_notes": "",
        "production_activation": False,
    }
    initial_review_template_sha = _digest(review_template)

    handoff_core = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "performer_name": performer_name,
        "strategy": strategy,
        "appearance_epoch_plan_sha256": plan_sha,
        "evidence_sha256": evidence_sha,
        "source_frame_index_model_set_sha256": model_set_sha,
        "identity_bank_sha256": identity_bank_sha,
        "identity_calibration_sha256": identity_calibration_sha,
        "eligible_observation_count": eligible_count,
        "eligible_train_observation_count": eligible_train_count,
        "eligible_evaluation_observation_count": eligible_evaluation_count,
        "source_group_count": source_group_count,
        "train_source_group_count": train_group_count,
        "evaluation_source_group_count": evaluation_group_count,
        "candidate_source_groups": candidates,
        "initial_review_template_sha256": initial_review_template_sha,
        "operator_requirements": {
            "assign_selected_epoch_id": True,
            "select_at_least_one_train_source_group": True,
            "select_at_least_one_evaluation_source_group": True,
            "set_reviewed_by": True,
            "set_human_review_complete_true": True,
            "set_human_approved_true_only_after_review": True,
            "keep_production_activation_false": True,
        },
        "review_command": (
            "bodyrig-photoreal-appearance-epoch-review --plan <PLAN> "
            "--human-review <COMPLETED_REVIEW> --out <SELECTION>"
        ),
        "human_review_complete": False,
        "human_approved": False,
        "teacher_input_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    handoff_core["appearance_epoch_review_handoff_sha256"] = _digest(handoff_core)
    return handoff_core, review_template


def build_appearance_epoch_review_handoff_files(
    plan_path: str | Path,
    handoff_output_path: str | Path,
    review_template_output_path: str | Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    plan = _read_json(plan_path, label="appearance epoch plan")
    handoff, review_template = build_appearance_epoch_review_handoff(plan)

    handoff_output = Path(handoff_output_path).expanduser().resolve()
    review_output = Path(review_template_output_path).expanduser().resolve()
    if handoff_output == review_output:
        raise PhotorealAppearanceEpochHandoffError("handoff and review template outputs must be different files")
    if handoff_output.exists():
        raise PhotorealAppearanceEpochHandoffError(f"appearance epoch review handoff already exists: {handoff_output}")
    if review_output.exists():
        raise PhotorealAppearanceEpochHandoffError(f"appearance epoch review template already exists: {review_output}")

    review_created = False
    handoff_created = False
    try:
        handoff_output.parent.mkdir(parents=True, exist_ok=True)
        review_output.parent.mkdir(parents=True, exist_ok=True)
        with review_output.open("x", encoding="utf-8") as handle:
            review_created = True
            handle.write(json.dumps(review_template, indent=2, sort_keys=True, allow_nan=False) + "\n")
        with handoff_output.open("x", encoding="utf-8") as handle:
            handoff_created = True
            handle.write(json.dumps(handoff, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except OSError as exc:
        if handoff_created:
            try:
                handoff_output.unlink()
            except OSError:
                pass
        if review_created:
            try:
                review_output.unlink()
            except OSError:
                pass
        raise PhotorealAppearanceEpochHandoffError("failed to persist appearance epoch review handoff") from exc

    return handoff, review_template
