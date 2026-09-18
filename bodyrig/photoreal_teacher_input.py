from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

PLAN_FORMAT = "bodyrig-photoreal-dataset-plan"
PLAN_VERSION = 1
RECEIPT_FORMAT = "bodyrig-photoreal-source-receipt"
RECEIPT_VERSION = 1
FRAME_INDEX_FORMAT = "bodyrig-photoreal-frame-index"
FRAME_INDEX_VERSION = 1
SELECTION_FORMAT = "bodyrig-photoreal-appearance-epoch-selection"
SELECTION_VERSION = 1
FORMAT = "bodyrig-photoreal-teacher-input"
VERSION = 1


class PhotorealTeacherInputError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealTeacherInputError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealTeacherInputError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    result = str(value or "").strip()
    if not result or len(result) > maximum:
        raise PhotorealTeacherInputError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = str(value or "").strip().lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealTeacherInputError(f"{label} is invalid")
    return result


def _digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _plan_sources(plan: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if plan.get("format") != PLAN_FORMAT or plan.get("version") != PLAN_VERSION:
        raise PhotorealTeacherInputError("dataset plan format/version mismatch")
    if plan.get("build_only") is not True or plan.get("runtime_dependency") is not False:
        raise PhotorealTeacherInputError("dataset plan authority boundary is invalid")
    if plan.get("production_activation") is not False:
        raise PhotorealTeacherInputError("dataset plan crossed production authority")
    result: dict[str, dict[str, Any]] = {}
    for split in ("train", "evaluation"):
        values = plan.get(split)
        if not isinstance(values, list) or not values:
            raise PhotorealTeacherInputError(f"dataset plan {split} is invalid")
        for raw in values:
            if not isinstance(raw, Mapping):
                raise PhotorealTeacherInputError("dataset plan source is invalid")
            source_key = _text(raw.get("source_id"), label="dataset source key")
            if source_key in result:
                raise PhotorealTeacherInputError(f"dataset plan repeats source key: {source_key}")
            item = dict(raw)
            item["split"] = split
            result[source_key] = item
    return result


def _receipt_sources(receipt: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    if receipt.get("format") != RECEIPT_FORMAT or receipt.get("version") != RECEIPT_VERSION:
        raise PhotorealTeacherInputError("source receipt format/version mismatch")
    if receipt.get("all_sources_readable") is not True or receipt.get("all_sources_sha256_bound") is not True:
        raise PhotorealTeacherInputError("source receipt is incomplete")
    if receipt.get("source_keys_path_specific") is not True:
        raise PhotorealTeacherInputError("source receipt lacks path-specific source keys")
    if receipt.get("build_only") is not True or receipt.get("runtime_dependency") is not False:
        raise PhotorealTeacherInputError("source receipt authority boundary is invalid")
    if receipt.get("production_activation") is not False:
        raise PhotorealTeacherInputError("source receipt crossed production authority")
    values = receipt.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealTeacherInputError("source receipt has no sources")
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherInputError("source receipt contains invalid source")
        source_key = _text(raw.get("source_key"), label="receipt source key")
        if source_key in result:
            raise PhotorealTeacherInputError(f"source receipt repeats source key: {source_key}")
        result[source_key] = {
            "kind": _text(raw.get("kind"), label="receipt source kind", maximum=16),
            "resolved_path": _text(raw.get("resolved_path"), label="resolved source path"),
            "size_bytes": int(raw.get("size_bytes") or 0),
            "sha256": _sha(raw.get("sha256"), label="source SHA-256"),
        }
    return result


def build_teacher_input(
    plan: Mapping[str, Any],
    receipt: Mapping[str, Any],
    frame_index: Mapping[str, Any],
    epoch_selection: Mapping[str, Any],
) -> dict[str, Any]:
    plan_sources = _plan_sources(plan)
    receipt_sources = _receipt_sources(receipt)
    if set(plan_sources) != set(receipt_sources):
        raise PhotorealTeacherInputError("dataset plan/source receipt source universe mismatch")

    performer_id = _text(plan.get("performer_id"), label="dataset performer id", maximum=256)
    if _text(receipt.get("performer_id"), label="receipt performer id", maximum=256) != performer_id:
        raise PhotorealTeacherInputError("dataset plan/source receipt performer mismatch")

    if frame_index.get("format") != FRAME_INDEX_FORMAT or frame_index.get("version") != FRAME_INDEX_VERSION:
        raise PhotorealTeacherInputError("frame index format/version mismatch")
    if str(frame_index.get("performer_id") or "") != performer_id:
        raise PhotorealTeacherInputError("frame index performer mismatch")
    if frame_index.get("teacher_training_authorized") is not True:
        raise PhotorealTeacherInputError("frame index does not authorize teacher training")
    if frame_index.get("photoreal_acceptance_authority") is not False or frame_index.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherInputError("frame index photoreal/human authority boundary is invalid")
    if frame_index.get("build_only") is not True or frame_index.get("runtime_dependency") is not False:
        raise PhotorealTeacherInputError("frame index build/runtime authority boundary is invalid")
    if frame_index.get("production_activation") is not False:
        raise PhotorealTeacherInputError("frame index crossed production authority")

    if epoch_selection.get("format") != SELECTION_FORMAT or epoch_selection.get("version") != SELECTION_VERSION:
        raise PhotorealTeacherInputError("appearance epoch selection format/version mismatch")
    if str(epoch_selection.get("performer_id") or "") != performer_id:
        raise PhotorealTeacherInputError("appearance epoch selection performer mismatch")
    if epoch_selection.get("human_epoch_review_complete") is not True or epoch_selection.get("human_approved") is not True:
        raise PhotorealTeacherInputError("appearance epoch selection lacks explicit human approval")
    if epoch_selection.get("teacher_input_authorized") is not True or epoch_selection.get("teacher_training_authorized") is not True:
        raise PhotorealTeacherInputError("appearance epoch selection does not authorize teacher input")
    if epoch_selection.get("photoreal_acceptance_authority") is not False or epoch_selection.get("human_visual_acceptance_required") is not True:
        raise PhotorealTeacherInputError("appearance epoch selection crossed photoreal/human authority")
    if epoch_selection.get("build_only") is not True or epoch_selection.get("runtime_dependency") is not False:
        raise PhotorealTeacherInputError("appearance epoch selection authority boundary is invalid")
    if epoch_selection.get("production_activation") is not False:
        raise PhotorealTeacherInputError("appearance epoch selection crossed production authority")

    selected_raw = epoch_selection.get("selected_source_group_ids")
    if not isinstance(selected_raw, list) or not selected_raw:
        raise PhotorealTeacherInputError("appearance epoch selection has no source groups")
    selected_groups = {_text(item, label="selected epoch source group") for item in selected_raw}

    frame_values = frame_index.get("observations")
    if not isinstance(frame_values, list) or not frame_values:
        raise PhotorealTeacherInputError("frame index contains no observations")
    selected_observations: list[dict[str, Any]] = []
    selected_source_keys: set[str] = set()
    eval_coverage: set[str] = set()
    all_coverage: set[str] = set()
    for raw in frame_values:
        if not isinstance(raw, Mapping):
            raise PhotorealTeacherInputError("frame index observation is invalid")
        if raw.get("eligible_for_teacher") is not True:
            continue
        group_id = _text(raw.get("group_id"), label="frame source group")
        if group_id not in selected_groups:
            continue
        if raw.get("target_identity_verified") is not True:
            raise PhotorealTeacherInputError("selected teacher observation lacks target identity authority")
        source_key = _text(raw.get("source_key"), label="frame source key")
        planned = plan_sources.get(source_key)
        bound = receipt_sources.get(source_key)
        if planned is None or bound is None:
            raise PhotorealTeacherInputError(f"selected observation references unknown source: {source_key}")
        split = _text(raw.get("split"), label="frame split", maximum=32)
        if split != planned["split"]:
            raise PhotorealTeacherInputError("frame split differs from dataset plan")
        coverage_raw = raw.get("coverage")
        if not isinstance(coverage_raw, list):
            raise PhotorealTeacherInputError("frame coverage is invalid")
        coverage = sorted({_text(item, label="frame coverage", maximum=64) for item in coverage_raw})
        all_coverage.update(coverage)
        if split == "evaluation":
            eval_coverage.update(coverage)
        selected_source_keys.add(source_key)
        selected_observations.append(
            {
                "source_key": source_key,
                "group_id": group_id,
                "split": split,
                "frame_sha256": _sha(raw.get("frame_sha256"), label="frame SHA-256"),
                "timestamp_seconds": raw.get("timestamp_seconds"),
                "eye": _text(raw.get("eye"), label="frame eye", maximum=16),
                "view_bin": _text(raw.get("view_bin"), label="frame view bin", maximum=64),
                "coverage": coverage,
            }
        )

    if not selected_observations:
        raise PhotorealTeacherInputError("approved appearance epoch contains no eligible observations")
    observed_groups = {item["group_id"] for item in selected_observations}
    if observed_groups != selected_groups:
        missing = sorted(selected_groups - observed_groups)
        raise PhotorealTeacherInputError(
            f"approved appearance epoch has selected groups without eligible observations ({len(missing)})"
        )

    required_raw = frame_index.get("held_out_view_coverage_required")
    if not isinstance(required_raw, list) or not required_raw:
        raise PhotorealTeacherInputError("frame index held-out coverage policy is invalid")
    required = {_text(item, label="held-out coverage requirement", maximum=64) for item in required_raw}
    if "full-body-rear" in all_coverage:
        required.add("full-body-rear")
    missing_coverage = sorted(required - eval_coverage)
    if missing_coverage:
        raise PhotorealTeacherInputError(
            "approved appearance epoch loses required held-out evaluation coverage: " + ", ".join(missing_coverage)
        )

    train_sources: list[dict[str, Any]] = []
    evaluation_sources: list[dict[str, Any]] = []
    for source_key in sorted(selected_source_keys):
        planned = plan_sources[source_key]
        bound = receipt_sources[source_key]
        record = {
            "source_key": source_key,
            "group_id": _text(planned.get("group_id"), label="dataset group id"),
            "kind": _text(planned.get("kind"), label="dataset source kind", maximum=16),
            "resolved_path": bound["resolved_path"],
            "size_bytes": bound["size_bytes"],
            "sha256": bound["sha256"],
            "information_score": float(planned.get("information_score") or 0.0),
            "width": int(planned.get("width") or 0),
            "height": int(planned.get("height") or 0),
            "projection": str(planned.get("projection") or "flat"),
            "stereo_layout": str(planned.get("stereo_layout") or "mono"),
        }
        if planned["split"] == "train":
            train_sources.append(record)
        else:
            evaluation_sources.append(record)
    if not train_sources or not evaluation_sources:
        raise PhotorealTeacherInputError("approved appearance epoch requires both train and evaluation sources")

    selected_observations.sort(
        key=lambda item: (
            str(item["split"]),
            str(item["group_id"]),
            str(item["source_key"]),
            -1.0 if item["timestamp_seconds"] is None else float(item["timestamp_seconds"]),
            str(item["eye"]),
        )
    )
    train_observations = [item for item in selected_observations if item["split"] == "train"]
    evaluation_observations = [item for item in selected_observations if item["split"] == "evaluation"]
    if not train_observations or not evaluation_observations:
        raise PhotorealTeacherInputError("approved appearance epoch requires train and evaluation observations")

    manifest = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "performer_name": str(plan.get("performer_name") or ""),
        "selected_epoch_id": _text(epoch_selection.get("selected_epoch_id"), label="selected epoch id", maximum=256),
        "appearance_epoch_selection_sha256": _sha(
            epoch_selection.get("appearance_epoch_selection_sha256"), label="appearance epoch selection SHA-256"
        ),
        "identity_bank_sha256": _sha(frame_index.get("identity_bank_sha256"), label="identity bank SHA-256"),
        "identity_calibration_sha256": _sha(
            frame_index.get("identity_calibration_sha256"), label="identity calibration SHA-256"
        ),
        "analyzer_model_set_sha256": _sha(
            frame_index.get("analyzer_model_set_sha256"), label="analyzer model-set SHA-256"
        ),
        "training_sources": train_sources,
        "held_out_evaluation_sources": evaluation_sources,
        "training_observations": train_observations,
        "held_out_evaluation_observations": evaluation_observations,
        "held_out_view_coverage_required": sorted(required),
        "held_out_view_coverage_observed": sorted(eval_coverage),
        "held_out_view_coverage_missing": [],
        "training_source_count": len(train_sources),
        "held_out_evaluation_source_count": len(evaluation_sources),
        "training_observation_count": len(train_observations),
        "held_out_evaluation_observation_count": len(evaluation_observations),
        "evaluation_bytes_excluded_from_teacher_request": True,
        "teacher_training_authorized": True,
        "photoreal_acceptance_authority": False,
        "human_visual_acceptance_required": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    manifest["teacher_input_sha256"] = _digest(manifest)
    return manifest


def build_teacher_input_files(
    plan_path: str | Path,
    receipt_path: str | Path,
    frame_index_path: str | Path,
    epoch_selection_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    plan = _read_json(plan_path, label="photoreal dataset plan")
    receipt = _read_json(receipt_path, label="photoreal source receipt")
    frame_index = _read_json(frame_index_path, label="photoreal frame index")
    selection = _read_json(epoch_selection_path, label="appearance epoch selection")
    result = build_teacher_input(plan, receipt, frame_index, selection)
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        raise PhotorealTeacherInputError(f"teacher input manifest already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result
