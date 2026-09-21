from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

from .photoreal_frame_authorized_observations_integrity import (
    PhotorealAuthorizedObservationsIntegrityError,
    validate_authorized_observations_integrity,
)
from .photoreal_frame_index import PhotorealFrameIndexError, build_frame_index
from .photoreal_p2_motion_input_plan import (
    PhotorealP2MotionInputPlanError,
    validate_motion_input_plan,
)
from .photoreal_p2_motion_normalization_selection import (
    PhotorealP2MotionNormalizationSelectionError,
    validate_normalization_selection,
)


FORMAT = "bodyrig-photoreal-p2-motion-window-selection"
VERSION = 1
SCAN_PLAN_FORMAT = "bodyrig-photoreal-scan-plan"
FRAME_INDEX_FORMAT = "bodyrig-photoreal-frame-index"
MIN_SIDE_SECONDS = 0.25
MAX_SIDE_SECONDS = 5.0
MAX_TOTAL_WINDOW_SECONDS = 8.0


class PhotorealP2MotionWindowSelectionError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2MotionWindowSelectionError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealP2MotionWindowSelectionError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealP2MotionWindowSelectionError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2MotionWindowSelectionError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealP2MotionWindowSelectionError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2MotionWindowSelectionError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2MotionWindowSelectionError(f"{label} format/version mismatch")


def _finite(value: Any, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2MotionWindowSelectionError(f"{label} is invalid")
    result = float(value)
    if not math.isfinite(result):
        raise PhotorealP2MotionWindowSelectionError(f"{label} is invalid")
    return result


def _side_seconds(value: Any, *, label: str) -> float:
    result = _finite(value, label=label)
    if not MIN_SIDE_SECONDS <= result <= MAX_SIDE_SECONDS:
        raise PhotorealP2MotionWindowSelectionError(
            f"{label} must be in {MIN_SIDE_SECONDS}..{MAX_SIDE_SECONDS} seconds"
        )
    return round(result, 6)


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    try:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window selection cannot be canonically serialized"
        ) from exc
    return hashlib.sha256(raw).hexdigest()


def _observation_ref(value: Mapping[str, Any]) -> str:
    payload = {
        "source_key": value["source_key"],
        "source_sha256": value["source_sha256"],
        "timestamp_seconds": value["timestamp_seconds"],
        "eye": value["eye"],
        "frame_sha256": value["frame_sha256"],
        "candidate_id": value["candidate_id"],
    }
    return "obs-" + hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()[:32]


def _strict_frame_index(
    dataset_plan: Mapping[str, Any],
    source_receipt: Mapping[str, Any],
    authorized_observations: Mapping[str, Any],
    persisted_frame_index: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        validate_authorized_observations_integrity(authorized_observations)
        rebuilt = build_frame_index(
            dataset_plan,
            source_receipt,
            authorized_observations,
        )
    except (
        PhotorealAuthorizedObservationsIntegrityError,
        PhotorealFrameIndexError,
    ) as exc:
        raise PhotorealP2MotionWindowSelectionError(
            f"P0 frame-index strict readback failed: {exc}"
        ) from exc
    if persisted_frame_index != rebuilt:
        raise PhotorealP2MotionWindowSelectionError(
            "persisted P0 frame index differs from strict recomputation"
        )
    if rebuilt.get("format") != FRAME_INDEX_FORMAT:
        raise PhotorealP2MotionWindowSelectionError("P0 frame index format mismatch")
    _strict_v1(rebuilt.get("version"), label="P0 frame index")
    if rebuilt.get("teacher_training_authorized") is not True:
        raise PhotorealP2MotionWindowSelectionError(
            "P0 frame index does not authorize the accepted source split"
        )
    if rebuilt.get("training_blockers") != []:
        raise PhotorealP2MotionWindowSelectionError(
            "P0 frame index still contains training blockers"
        )
    if rebuilt.get("production_activation") is not False:
        raise PhotorealP2MotionWindowSelectionError(
            "P0 frame index crossed production authority"
        )
    return rebuilt


def _scan_sources(scan_plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if scan_plan.get("format") != SCAN_PLAN_FORMAT:
        raise PhotorealP2MotionWindowSelectionError("P0 scan plan format/version mismatch")
    _strict_v1(scan_plan.get("version"), label="P0 scan plan")
    if scan_plan.get("strategy") != "uniform-midpoint-scout-v1":
        raise PhotorealP2MotionWindowSelectionError("P0 scan plan strategy mismatch")
    if scan_plan.get("all_sources_sha256_bound") is not True:
        raise PhotorealP2MotionWindowSelectionError("P0 scan plan is not source-SHA bound")
    if scan_plan.get("train_evaluation_assignment_inherited") is not True:
        raise PhotorealP2MotionWindowSelectionError("P0 scan plan lost split authority")
    if scan_plan.get("production_activation") is not False:
        raise PhotorealP2MotionWindowSelectionError("P0 scan plan crossed production authority")
    values = scan_plan.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealP2MotionWindowSelectionError("P0 scan plan has no sources")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionWindowSelectionError("P0 scan-plan source is invalid")
        key = _text(raw.get("source_key"), label="P0 scan-plan source key")
        if key in result:
            raise PhotorealP2MotionWindowSelectionError("P0 scan plan repeats source key")
        result[key] = raw
    return result


def _duration_from_scan_source(source: Mapping[str, Any]) -> float:
    if source.get("kind") != "video":
        raise PhotorealP2MotionWindowSelectionError("P2 motion window requires video source")
    raw_samples = source.get("samples")
    if not isinstance(raw_samples, list) or not raw_samples:
        raise PhotorealP2MotionWindowSelectionError("P0 scan source has no samples")
    timestamps: set[float] = set()
    for raw in raw_samples:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionWindowSelectionError("P0 scan sample is invalid")
        timestamp = _finite(
            raw.get("timestamp_seconds"),
            label="P0 scan sample timestamp",
        )
        if timestamp < 0:
            raise PhotorealP2MotionWindowSelectionError("P0 scan sample timestamp is negative")
        timestamps.add(round(timestamp, 6))
    ordered = sorted(timestamps)
    if len(ordered) < 2:
        raise PhotorealP2MotionWindowSelectionError(
            "P0 scan source cannot reconstruct canonical video duration"
        )
    duration = round(ordered[0] + ordered[-1], 6)
    if duration <= ordered[-1]:
        raise PhotorealP2MotionWindowSelectionError(
            "P0 scan source reconstructed duration is invalid"
        )
    return duration


def _candidate_universe(
    input_plan: Mapping[str, Any],
    normalization: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
    frame_index: Mapping[str, Any],
) -> list[dict[str, Any]]:
    scan_sources = _scan_sources(scan_plan)
    norm_by_ref = {
        str(item["source_ref"]): item
        for item in normalization["selections"]
        if isinstance(item, Mapping)
    }
    observations = frame_index.get("observations")
    if not isinstance(observations, list) or not observations:
        raise PhotorealP2MotionWindowSelectionError("P0 frame index has no observations")

    result: list[dict[str, Any]] = []
    for task in list(input_plan["motion_driver_tasks"]) + list(
        input_plan["held_out_motion_validation_tasks"]
    ):
        if not isinstance(task, Mapping):
            raise PhotorealP2MotionWindowSelectionError("P2 motion input task is invalid")
        source_ref = _text(task.get("source_ref"), label="P2 motion source ref", maximum=64)
        source_key = _text(task.get("source_key"), label="P2 motion source key")
        norm = norm_by_ref.get(source_ref)
        if norm is None:
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion normalization omitted selected source"
            )
        scan_source = scan_sources.get(source_key)
        if scan_source is None:
            raise PhotorealP2MotionWindowSelectionError(
                "P2 selected motion source is absent from P0 scan plan"
            )
        for field in ("split", "group_id", "source_sha256"):
            scan_value = scan_source.get("source_sha256" if field == "source_sha256" else field)
            if scan_value != task.get(field):
                raise PhotorealP2MotionWindowSelectionError(
                    f"P2 motion window/P0 scan binding mismatch: {field}"
                )
        duration = _duration_from_scan_source(scan_source)
        selected_eye = norm.get("selected_eye")
        candidates: list[dict[str, Any]] = []
        for obs in observations:
            if not isinstance(obs, Mapping):
                continue
            if (
                obs.get("source_key") != source_key
                or obs.get("source_sha256") != task.get("source_sha256")
                or obs.get("split") != task.get("split")
                or obs.get("group_id") != task.get("group_id")
                or obs.get("kind") != "video"
                or obs.get("eye") != selected_eye
                or obs.get("target_identity_verified") is not True
                or obs.get("eligible_for_teacher") is not True
            ):
                continue
            timestamp_raw = obs.get("timestamp_seconds")
            if timestamp_raw is None:
                continue
            timestamp = round(
                _finite(timestamp_raw, label="P0 target observation timestamp"),
                6,
            )
            if not 0 <= timestamp <= duration:
                continue
            candidate = {
                "observation_ref": _observation_ref(obs),
                "timestamp_seconds": timestamp,
                "eye": selected_eye,
                "frame_sha256": _sha(
                    obs.get("frame_sha256"),
                    label="P0 target observation frame SHA-256",
                ),
                "candidate_id": _text(
                    obs.get("candidate_id"),
                    label="P0 target observation candidate id",
                    maximum=128,
                ),
                "view_bin": _text(
                    obs.get("view_bin"),
                    label="P0 target observation view bin",
                    maximum=64,
                ),
                "coverage": sorted(
                    _text(item, label="P0 target observation coverage", maximum=64)
                    for item in (obs.get("coverage") or [])
                ),
            }
            candidates.append(candidate)
        unique = {item["observation_ref"]: item for item in candidates}
        candidates = sorted(
            unique.values(),
            key=lambda item: (
                item["timestamp_seconds"],
                item["candidate_id"],
            ),
        )
        if not candidates:
            raise PhotorealP2MotionWindowSelectionError(
                f"P2 motion source has no eligible P0 target observation for selected eye: {source_ref}"
            )
        result.append(
            {
                "source_ref": source_ref,
                "source_key": source_key,
                "split": task["split"],
                "role": task["role"],
                "source_sha256": task["source_sha256"],
                "selected_eye": selected_eye,
                "selected_viewport_id": norm.get("selected_viewport_id"),
                "source_duration_seconds": duration,
                "candidate_count": len(candidates),
                "candidates": candidates,
            }
        )
    return sorted(result, key=lambda item: item["source_ref"])


def describe_motion_window_candidates(
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
    source_selection: Mapping[str, Any],
    input_plan: Mapping[str, Any],
    normalization_selection: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
    dataset_plan: Mapping[str, Any],
    source_receipt: Mapping[str, Any],
    authorized_observations: Mapping[str, Any],
    frame_index: Mapping[str, Any],
) -> list[dict[str, Any]]:
    try:
        plan = validate_motion_input_plan(
            input_plan,
            handoff=handoff,
            private_index=private_index,
            selection=source_selection,
        )
        normalization = validate_normalization_selection(
            normalization_selection,
            input_plan=plan,
        )
    except (
        PhotorealP2MotionInputPlanError,
        PhotorealP2MotionNormalizationSelectionError,
    ) as exc:
        raise PhotorealP2MotionWindowSelectionError(
            f"P2 motion window authority readback failed: {exc}"
        ) from exc
    strict_index = _strict_frame_index(
        dataset_plan,
        source_receipt,
        authorized_observations,
        frame_index,
    )
    if strict_index.get("performer_id") != plan.get("performer_id"):
        raise PhotorealP2MotionWindowSelectionError(
            "P0 frame index performer differs from P2 motion plan"
        )
    return _candidate_universe(plan, normalization, scan_plan, strict_index)


def build_motion_window_selection(
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
    source_selection: Mapping[str, Any],
    input_plan: Mapping[str, Any],
    normalization_selection: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
    dataset_plan: Mapping[str, Any],
    source_receipt: Mapping[str, Any],
    authorized_observations: Mapping[str, Any],
    frame_index: Mapping[str, Any],
    *,
    choices: Mapping[str, Mapping[str, Any]],
    reviewed_by: str,
    review_notes: str,
    approve_human_selection: bool,
) -> dict[str, Any]:
    if approve_human_selection is not True:
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window selection requires explicit human approval"
        )
    reviewer = _text(reviewed_by, label="P2 motion window reviewer", maximum=256)
    if not isinstance(review_notes, str) or not review_notes.strip() or len(review_notes) > 8192:
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window review notes are invalid"
        )
    universes = describe_motion_window_candidates(
        handoff,
        private_index,
        source_selection,
        input_plan,
        normalization_selection,
        scan_plan,
        dataset_plan,
        source_receipt,
        authorized_observations,
        frame_index,
    )
    choice_map = dict(choices)
    if set(choice_map) != {item["source_ref"] for item in universes}:
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window choices must cover every selected source exactly"
        )

    selections: list[dict[str, Any]] = []
    for universe in universes:
        ref = universe["source_ref"]
        raw = choice_map[ref]
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window choice is invalid"
            )
        observation_ref = _text(
            raw.get("observation_ref"),
            label="P2 motion window observation ref",
            maximum=64,
        )
        candidate = next(
            (
                item
                for item in universe["candidates"]
                if item["observation_ref"] == observation_ref
            ),
            None,
        )
        if candidate is None:
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window observation is outside authorized candidate universe"
            )
        before = _side_seconds(
            raw.get("before_seconds"),
            label="P2 motion window before_seconds",
        )
        after = _side_seconds(
            raw.get("after_seconds"),
            label="P2 motion window after_seconds",
        )
        if before + after > MAX_TOTAL_WINDOW_SECONDS:
            raise PhotorealP2MotionWindowSelectionError(
                f"P2 motion window exceeds {MAX_TOTAL_WINDOW_SECONDS} seconds"
            )
        anchor = candidate["timestamp_seconds"]
        start = round(anchor - before, 6)
        end = round(anchor + after, 6)
        duration = universe["source_duration_seconds"]
        if start < 0 or end > duration or end <= start:
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window is outside canonical source duration"
            )
        selections.append(
            {
                "source_ref": ref,
                "source_key": universe["source_key"],
                "split": universe["split"],
                "role": universe["role"],
                "source_sha256": universe["source_sha256"],
                "selected_eye": universe["selected_eye"],
                "selected_viewport_id": universe["selected_viewport_id"],
                "source_duration_seconds": duration,
                "observation_ref": observation_ref,
                "anchor_timestamp_seconds": anchor,
                "anchor_frame_sha256": candidate["frame_sha256"],
                "anchor_candidate_id": candidate["candidate_id"],
                "anchor_view_bin": candidate["view_bin"],
                "anchor_coverage": candidate["coverage"],
                "window_before_seconds": before,
                "window_after_seconds": after,
                "window_start_seconds": start,
                "window_end_seconds": end,
                "window_duration_seconds": round(end - start, 6),
                "human_selected": True,
            }
        )

    selections.sort(key=lambda item: item["source_ref"])
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": input_plan["performer_id"],
        "selected_epoch_id": input_plan["selected_epoch_id"],
        "teacher_input_sha256": input_plan["teacher_input_sha256"],
        "p2_motion_input_plan_sha256": input_plan["p2_motion_input_plan_sha256"],
        "p2_motion_normalization_selection_sha256": normalization_selection[
            "p2_motion_normalization_selection_sha256"
        ],
        "selection_count": len(selections),
        "selections": selections,
        "maximum_total_window_seconds": MAX_TOTAL_WINDOW_SECONDS,
        "human_motion_window_selection_required": True,
        "human_motion_window_selection_complete": True,
        "reviewed_by": reviewer,
        "review_notes": review_notes.strip(),
        "source_media_rehash_performed": False,
        "motion_input_preparation_execution_authorized": True,
        "p2_animation_execution_authorized": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p2_motion_window_selection_sha256"] = _digest(
        result,
        omit="p2_motion_window_selection_sha256",
    )
    return validate_motion_window_selection(
        result,
        input_plan=input_plan,
        normalization_selection=normalization_selection,
    )


def validate_motion_window_selection(
    value: Mapping[str, Any],
    *,
    input_plan: Mapping[str, Any],
    normalization_selection: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_motion_input_plan_sha256",
        "p2_motion_normalization_selection_sha256",
        "selection_count",
        "selections",
        "maximum_total_window_seconds",
        "human_motion_window_selection_required",
        "human_motion_window_selection_complete",
        "reviewed_by",
        "review_notes",
        "source_media_rehash_performed",
        "motion_input_preparation_execution_authorized",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_motion_window_selection_sha256",
    }
    if set(value) != expected:
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window selection fields must match v1 exactly"
        )
    if value.get("format") != FORMAT:
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window selection format/version mismatch"
        )
    _strict_v1(value.get("version"), label="P2 motion window selection")
    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_motion_input_plan_sha256",
    ):
        if value.get(field) != input_plan.get(field):
            raise PhotorealP2MotionWindowSelectionError(
                f"P2 motion window selection lineage mismatch: {field}"
            )
    if value.get("p2_motion_normalization_selection_sha256") != normalization_selection.get(
        "p2_motion_normalization_selection_sha256"
    ):
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window normalization lineage mismatch"
        )
    if value.get("maximum_total_window_seconds") != MAX_TOTAL_WINDOW_SECONDS:
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window maximum duration policy mismatch"
        )
    declared = _sha(
        value.get("p2_motion_window_selection_sha256"),
        label="P2 motion window selection SHA-256",
    )
    if _digest(value, omit="p2_motion_window_selection_sha256") != declared:
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window selection digest mismatch"
        )
    selections = value.get("selections")
    count = value.get("selection_count")
    if (
        not isinstance(selections, list)
        or not selections
        or isinstance(count, bool)
        or not isinstance(count, int)
        or count != len(selections)
    ):
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window selection count mismatch"
        )
    input_tasks = {
        str(item["source_ref"]): item
        for item in list(input_plan["motion_driver_tasks"])
        + list(input_plan["held_out_motion_validation_tasks"])
        if isinstance(item, Mapping)
    }
    normalization_by_ref = {
        str(item["source_ref"]): item
        for item in normalization_selection.get("selections", [])
        if isinstance(item, Mapping)
    }
    expected_refs = set(input_tasks)
    if set(normalization_by_ref) != expected_refs:
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window normalization source universe mismatch"
        )
    seen: set[str] = set()
    for raw in selections:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window selection record is invalid"
            )
        fields = {
            "source_ref",
            "source_key",
            "split",
            "role",
            "source_sha256",
            "selected_eye",
            "selected_viewport_id",
            "source_duration_seconds",
            "observation_ref",
            "anchor_timestamp_seconds",
            "anchor_frame_sha256",
            "anchor_candidate_id",
            "anchor_view_bin",
            "anchor_coverage",
            "window_before_seconds",
            "window_after_seconds",
            "window_start_seconds",
            "window_end_seconds",
            "window_duration_seconds",
            "human_selected",
        }
        if set(raw) != fields:
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window selection record fields must match v1 exactly"
            )
        ref = _text(raw.get("source_ref"), label="P2 motion window source ref", maximum=64)
        if ref in seen or ref not in expected_refs:
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window source universe mismatch"
            )
        seen.add(ref)
        task = input_tasks[ref]
        norm = normalization_by_ref[ref]
        for field in ("source_key", "split", "role", "source_sha256"):
            if raw.get(field) != task.get(field):
                raise PhotorealP2MotionWindowSelectionError(
                    f"P2 motion window/input-plan binding mismatch: {field}"
                )
        if raw.get("selected_eye") != norm.get("selected_eye"):
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window selected eye differs from normalization authority"
            )
        if raw.get("selected_viewport_id") != norm.get("selected_viewport_id"):
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window selected viewport differs from normalization authority"
            )
        observation_ref = _text(
            raw.get("observation_ref"),
            label="P2 motion window observation ref",
            maximum=64,
        )
        if not observation_ref.startswith("obs-"):
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window observation ref is not canonical"
            )
        duration = _finite(
            raw.get("source_duration_seconds"),
            label="P2 motion source duration",
        )
        anchor = _finite(
            raw.get("anchor_timestamp_seconds"),
            label="P2 motion window anchor timestamp",
        )
        before = _side_seconds(
            raw.get("window_before_seconds"),
            label="P2 motion window before_seconds",
        )
        after = _side_seconds(
            raw.get("window_after_seconds"),
            label="P2 motion window after_seconds",
        )
        start = _finite(
            raw.get("window_start_seconds"),
            label="P2 motion window start",
        )
        end = _finite(
            raw.get("window_end_seconds"),
            label="P2 motion window end",
        )
        window_duration = _finite(
            raw.get("window_duration_seconds"),
            label="P2 motion window duration",
        )
        if before + after > MAX_TOTAL_WINDOW_SECONDS:
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window exceeds maximum duration"
            )
        if (
            round(anchor - before, 6) != round(start, 6)
            or round(anchor + after, 6) != round(end, 6)
            or round(end - start, 6) != round(window_duration, 6)
            or start < 0
            or end > duration
            or end <= start
        ):
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window timing is internally inconsistent"
            )
        _sha(raw.get("anchor_frame_sha256"), label="P2 motion window anchor frame SHA-256")
        _text(raw.get("observation_ref"), label="P2 motion window observation ref", maximum=64)
        _text(raw.get("anchor_candidate_id"), label="P2 motion window candidate id", maximum=128)
        _text(raw.get("anchor_view_bin"), label="P2 motion window view bin", maximum=64)
        coverage = raw.get("anchor_coverage")
        if not isinstance(coverage, list) or any(not isinstance(item, str) or not item for item in coverage):
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window anchor coverage is invalid"
            )
        if coverage != sorted(set(coverage)):
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window anchor coverage is not canonical"
            )
        if raw.get("human_selected") is not True:
            raise PhotorealP2MotionWindowSelectionError(
                "P2 motion window must remain explicitly human selected"
            )
    if seen != expected_refs:
        raise PhotorealP2MotionWindowSelectionError(
            "P2 motion window selection omitted selected source"
        )
    _text(value.get("reviewed_by"), label="P2 motion window reviewer", maximum=256)
    notes = value.get("review_notes")
    if not isinstance(notes, str) or not notes.strip() or len(notes) > 8192:
        raise PhotorealP2MotionWindowSelectionError("P2 motion window review notes are invalid")
    for field, expected_value in (
        ("human_motion_window_selection_required", True),
        ("human_motion_window_selection_complete", True),
        ("source_media_rehash_performed", False),
        ("motion_input_preparation_execution_authorized", True),
        ("p2_animation_execution_authorized", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected_value:
            raise PhotorealP2MotionWindowSelectionError(
                f"P2 motion window selection authority mismatch: {field}"
            )
    return dict(value)


def load_p0_artifacts(p0_root: str | Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = Path(p0_root).expanduser().resolve()
    if not root.is_dir():
        raise PhotorealP2MotionWindowSelectionError(f"P0 root not found: {root}")
    return (
        _read_json(root / "scan-plan.json", label="P0 scan plan"),
        _read_json(root / "dataset-plan.json", label="P0 dataset plan"),
        _read_json(root / "source-receipt.json", label="P0 source receipt"),
        _read_json(
            root / "frame-authorized-observations.json",
            label="P0 authorized frame observations",
        ),
        _read_json(root / "frame-index.json", label="P0 frame index"),
    )
