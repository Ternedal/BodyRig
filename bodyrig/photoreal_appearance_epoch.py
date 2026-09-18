from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

FRAME_INDEX_FORMAT = "bodyrig-photoreal-frame-index"
FRAME_INDEX_VERSION = 1
FORMAT = "bodyrig-photoreal-appearance-epoch-plan"
VERSION = 1


class PhotorealAppearanceEpochError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealAppearanceEpochError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealAppearanceEpochError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealAppearanceEpochError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum:
        raise PhotorealAppearanceEpochError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise PhotorealAppearanceEpochError(f"{label} is invalid")
    result = value.strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealAppearanceEpochError(f"{label} is invalid")
    return result


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_appearance_epoch_plan(
    frame_index: Mapping[str, Any],
    *,
    strategy: str = "human-review-required-v1",
) -> dict[str, Any]:
    frame_index_version = frame_index.get("version")
    if (
        frame_index.get("format") != FRAME_INDEX_FORMAT
        or isinstance(frame_index_version, bool)
        or not isinstance(frame_index_version, (int, float))
        or frame_index_version != FRAME_INDEX_VERSION
    ):
        raise PhotorealAppearanceEpochError("photoreal frame index format/version mismatch")
    if frame_index.get("teacher_training_authorized") is not True:
        raise PhotorealAppearanceEpochError("appearance epoch planning requires a teacher-training-authorized frame index")
    if frame_index.get("photoreal_acceptance_authority") is not False:
        raise PhotorealAppearanceEpochError("frame index crossed photoreal acceptance authority")
    if frame_index.get("human_visual_acceptance_required") is not True:
        raise PhotorealAppearanceEpochError("frame index human visual authority boundary is invalid")
    if frame_index.get("build_only") is not True or frame_index.get("runtime_dependency") is not False:
        raise PhotorealAppearanceEpochError("frame index build/runtime authority boundary is invalid")
    if frame_index.get("production_activation") is not False:
        raise PhotorealAppearanceEpochError("frame index crossed production authority")

    performer_id = _text(frame_index.get("performer_id"), label="performer id", maximum=256)
    analyzer_model_sha = _sha(
        frame_index.get("analyzer_model_set_sha256"), label="frame analyzer model-set SHA-256"
    )
    identity_bank_sha = _sha(frame_index.get("identity_bank_sha256"), label="identity bank SHA-256")
    identity_calibration_sha = _sha(
        frame_index.get("identity_calibration_sha256"), label="identity calibration SHA-256"
    )
    observations = frame_index.get("observations")
    if not isinstance(observations, list) or not observations:
        raise PhotorealAppearanceEpochError("frame index contains no observations")

    eligible: list[dict[str, Any]] = []
    group_stats: dict[str, dict[str, Any]] = {}
    split_counts = {"train": 0, "evaluation": 0}
    for raw in observations:
        if not isinstance(raw, Mapping):
            raise PhotorealAppearanceEpochError("frame index contains a non-object observation")
        if raw.get("eligible_for_teacher") is not True:
            continue
        if raw.get("target_identity_verified") is not True:
            raise PhotorealAppearanceEpochError("teacher-eligible frame lacks target identity authority")
        split = _text(raw.get("split"), label="observation split", maximum=32)
        if split not in split_counts:
            raise PhotorealAppearanceEpochError(f"unsupported observation split: {split}")
        source_key = _text(raw.get("source_key"), label="source key")
        group_id = _text(raw.get("group_id"), label="source group id")
        frame_sha = _sha(raw.get("frame_sha256"), label="frame SHA-256")
        view_bin = _text(raw.get("view_bin"), label="view bin", maximum=64)
        eligible.append(
            {
                "source_key": source_key,
                "group_id": group_id,
                "split": split,
                "frame_sha256": frame_sha,
                "timestamp_seconds": raw.get("timestamp_seconds"),
                "eye": _text(raw.get("eye"), label="observation eye", maximum=16),
                "view_bin": view_bin,
            }
        )
        existing = group_stats.get(group_id)
        if existing is None:
            existing = {
                "group_id": group_id,
                "split": split,
                "source_keys": set(),
                "frame_sha256s": set(),
                "view_bins": set(),
                "eligible_observation_count": 0,
            }
            group_stats[group_id] = existing
        elif existing["split"] != split:
            raise PhotorealAppearanceEpochError("source group crosses train/evaluation boundary")
        existing["source_keys"].add(source_key)
        existing["frame_sha256s"].add(frame_sha)
        existing["view_bins"].add(view_bin)
        existing["eligible_observation_count"] += 1
        split_counts[split] += 1

    if not eligible or split_counts["train"] == 0 or split_counts["evaluation"] == 0:
        raise PhotorealAppearanceEpochError("appearance epoch planning requires eligible train and evaluation evidence")

    eligible.sort(
        key=lambda item: (
            str(item["split"]),
            str(item["group_id"]),
            str(item["source_key"]),
            -1.0 if item["timestamp_seconds"] is None else float(item["timestamp_seconds"]),
            str(item["eye"]),
        )
    )
    eligible_source_groups = [
        {
            "group_id": group_id,
            "split": str(value["split"]),
            "source_keys": sorted(str(item) for item in value["source_keys"]),
            "frame_sha256s": sorted(str(item) for item in value["frame_sha256s"]),
            "view_bins": sorted(str(item) for item in value["view_bins"]),
            "eligible_observation_count": int(value["eligible_observation_count"]),
        }
        for group_id, value in sorted(group_stats.items())
    ]
    evidence_digest = _digest(
        {
            "performer_id": performer_id,
            "analyzer_model_set_sha256": analyzer_model_sha,
            "identity_bank_sha256": identity_bank_sha,
            "identity_calibration_sha256": identity_calibration_sha,
            "eligible": eligible,
        }
    )
    performer_name = frame_index.get("performer_name")
    if performer_name is None:
        performer_name = ""
    elif not isinstance(performer_name, str):
        raise PhotorealAppearanceEpochError("performer name is invalid")

    plan_core = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "performer_name": performer_name,
        "strategy": _text(strategy, label="appearance epoch strategy", maximum=128),
        "source_frame_index_model_set_sha256": analyzer_model_sha,
        "identity_bank_sha256": identity_bank_sha,
        "identity_calibration_sha256": identity_calibration_sha,
        "eligible_observation_count": len(eligible),
        "eligible_train_observation_count": split_counts["train"],
        "eligible_evaluation_observation_count": split_counts["evaluation"],
        "source_group_count": len(eligible_source_groups),
        "eligible_source_groups": eligible_source_groups,
        "evidence_sha256": evidence_digest,
        "candidate_epochs": [],
        "selected_epoch_id": None,
        "human_epoch_review_required": True,
        "human_epoch_review_complete": False,
        "teacher_input_authorized": False,
        "teacher_training_authorized": False,
        "photoreal_acceptance_authority": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    plan_core["appearance_epoch_plan_sha256"] = _digest(plan_core)
    return plan_core


def build_appearance_epoch_plan_file(
    frame_index_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    frame_index = _read_json(frame_index_path, label="photoreal frame index")
    result = build_appearance_epoch_plan(frame_index)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealAppearanceEpochError(f"appearance epoch plan already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
