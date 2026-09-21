from __future__ import annotations

import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from .photoreal_equirectangular_deprojection import (
    PhotorealEquirectangularDeprojectionError,
    build_equirectangular_viewports,
)
from .photoreal_p2_motion_input_plan import (
    PhotorealP2MotionInputPlanError,
    validate_motion_input_plan,
)
from .photoreal_scan_plan import FORMAT as SCAN_PLAN_FORMAT


FORMAT = "bodyrig-photoreal-p2-motion-normalization-selection"
VERSION = 1


class PhotorealP2MotionNormalizationSelectionError(ValueError):
    pass


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealP2MotionNormalizationSelectionError(f"{label} is invalid")
    result = value.strip()
    if not result or len(result) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2MotionNormalizationSelectionError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(ch not in "0123456789abcdef" for ch in result):
        raise PhotorealP2MotionNormalizationSelectionError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2MotionNormalizationSelectionError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2MotionNormalizationSelectionError(f"{label} format/version mismatch")


def _digest(value: Mapping[str, Any], *, omit: str | None = None) -> str:
    payload = dict(value)
    if omit is not None:
        payload.pop(omit, None)
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _scan_sources(scan_plan: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    if scan_plan.get("format") != SCAN_PLAN_FORMAT:
        raise PhotorealP2MotionNormalizationSelectionError("P0 scan plan format/version mismatch")
    _strict_v1(scan_plan.get("version"), label="P0 scan plan")
    if scan_plan.get("all_sources_sha256_bound") is not True:
        raise PhotorealP2MotionNormalizationSelectionError("P0 scan plan is not source-SHA bound")
    if scan_plan.get("train_evaluation_assignment_inherited") is not True:
        raise PhotorealP2MotionNormalizationSelectionError("P0 scan plan lost train/evaluation assignment")
    if scan_plan.get("production_activation") is not False:
        raise PhotorealP2MotionNormalizationSelectionError("P0 scan plan crossed production authority")
    values = scan_plan.get("sources")
    if not isinstance(values, list) or not values:
        raise PhotorealP2MotionNormalizationSelectionError("P0 scan plan has no sources")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionNormalizationSelectionError("P0 scan-plan source is invalid")
        key = _text(raw.get("source_key"), label="P0 scan-plan source key")
        if key in result:
            raise PhotorealP2MotionNormalizationSelectionError("P0 scan plan repeats source key")
        result[key] = raw
    return result


def _eyes(stereo_layout: str) -> list[str]:
    if stereo_layout == "mono":
        return ["mono"]
    if stereo_layout in {"side-by-side", "over-under"}:
        return ["left", "right"]
    raise PhotorealP2MotionNormalizationSelectionError(
        f"P2 motion normalization does not support stereo layout: {stereo_layout}"
    )


def _choice_universe(task: Mapping[str, Any], scan_source: Mapping[str, Any]) -> dict[str, Any]:
    for field in ("source_key", "group_id", "split", "source_sha256"):
        observed = scan_source.get("source_sha256" if field == "source_sha256" else field)
        if observed != task.get(field):
            raise PhotorealP2MotionNormalizationSelectionError(
                f"P2 motion normalization scan binding mismatch: {field}"
            )
    projection = _text(scan_source.get("projection"), label="P2 motion projection", maximum=128)
    stereo = _text(scan_source.get("stereo_layout"), label="P2 motion stereo layout", maximum=128)
    allowed_eyes = _eyes(stereo)

    if projection == "flat":
        strategy = "direct-flat-mono" if stereo == "mono" else "rectilinear-stereo-split"
        viewport_ids: list[str] = []
    elif projection == "equi":
        authority = scan_source.get("projection_authority")
        if not isinstance(authority, Mapping):
            raise PhotorealP2MotionNormalizationSelectionError(
                "equirectangular P2 motion source lacks projection authority"
            )
        try:
            viewports = build_equirectangular_viewports(authority)
        except PhotorealEquirectangularDeprojectionError as exc:
            raise PhotorealP2MotionNormalizationSelectionError(
                f"equirectangular P2 viewport authority is invalid: {exc}"
            ) from exc
        viewport_ids = [str(item["viewport_id"]) for item in viewports]
        strategy = "equirectangular-deprojection"
    else:
        raise PhotorealP2MotionNormalizationSelectionError(
            f"P2 motion normalization projection is not yet execution-authoritative: {projection}"
        )

    return {
        "source_ref": _text(task.get("source_ref"), label="P2 motion source ref", maximum=64),
        "source_key": _text(task.get("source_key"), label="P2 motion source key"),
        "split": _text(task.get("split"), label="P2 motion split", maximum=32),
        "role": _text(task.get("role"), label="P2 motion role", maximum=64),
        "projection": projection,
        "stereo_layout": stereo,
        "normalization_strategy": strategy,
        "allowed_eyes": allowed_eyes,
        "allowed_viewport_ids": viewport_ids,
        "human_selection_required": len(allowed_eyes) > 1 or len(viewport_ids) > 1,
    }


def build_normalization_selection(
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
    source_selection: Mapping[str, Any],
    input_plan: Mapping[str, Any],
    scan_plan: Mapping[str, Any],
    *,
    choices: Mapping[str, Mapping[str, Any]] | None,
    reviewed_by: str,
    review_notes: str,
    approve_human_selection: bool,
) -> dict[str, Any]:
    try:
        plan = validate_motion_input_plan(
            input_plan,
            handoff=handoff,
            private_index=private_index,
            selection=source_selection,
        )
    except PhotorealP2MotionInputPlanError as exc:
        raise PhotorealP2MotionNormalizationSelectionError(
            f"P2 motion input plan strict readback failed: {exc}"
        ) from exc

    if _text(scan_plan.get("performer_id"), label="P0 scan-plan performer", maximum=256) != plan["performer_id"]:
        raise PhotorealP2MotionNormalizationSelectionError("P0 scan plan performer differs from P2 motion plan")
    scan_sources = _scan_sources(scan_plan)
    universes: list[dict[str, Any]] = []
    for raw in list(plan["motion_driver_tasks"]) + list(plan["held_out_motion_validation_tasks"]):
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionNormalizationSelectionError("P2 motion input task is invalid")
        source_key = _text(raw.get("source_key"), label="P2 motion source key")
        scan_source = scan_sources.get(source_key)
        if scan_source is None:
            raise PhotorealP2MotionNormalizationSelectionError("P2 selected source is absent from P0 scan plan")
        universes.append(_choice_universe(raw, scan_source))

    human_required = any(item["human_selection_required"] for item in universes)
    if human_required and approve_human_selection is not True:
        raise PhotorealP2MotionNormalizationSelectionError(
            "P2 motion normalization requires explicit human eye/viewport approval"
        )
    reviewer = _text(reviewed_by, label="P2 motion normalization reviewer", maximum=256)
    if not isinstance(review_notes, str) or not review_notes.strip() or len(review_notes) > 8192:
        raise PhotorealP2MotionNormalizationSelectionError("P2 motion normalization review notes are invalid")

    supplied = choices or {}
    records: list[dict[str, Any]] = []
    for universe in universes:
        ref = universe["source_ref"]
        raw_choice = supplied.get(ref)
        if universe["human_selection_required"]:
            if not isinstance(raw_choice, Mapping):
                raise PhotorealP2MotionNormalizationSelectionError(
                    f"P2 motion normalization choice is missing for {ref}"
                )
            eye = _text(raw_choice.get("eye"), label="P2 motion selected eye", maximum=16)
            viewport_raw = raw_choice.get("viewport_id")
            viewport = None if viewport_raw is None else _text(
                viewport_raw,
                label="P2 motion selected viewport",
                maximum=64,
            )
            human_selected = True
        else:
            eye = universe["allowed_eyes"][0]
            viewport = universe["allowed_viewport_ids"][0] if universe["allowed_viewport_ids"] else None
            human_selected = False
            if raw_choice is not None:
                raise PhotorealP2MotionNormalizationSelectionError(
                    f"P2 motion normalization choice must not override deterministic source {ref}"
                )

        if eye not in universe["allowed_eyes"]:
            raise PhotorealP2MotionNormalizationSelectionError("P2 motion selected eye is outside authorized universe")
        allowed_viewports = universe["allowed_viewport_ids"]
        if allowed_viewports:
            if viewport not in allowed_viewports:
                raise PhotorealP2MotionNormalizationSelectionError(
                    "P2 motion selected viewport is outside authorized universe"
                )
        elif viewport is not None:
            raise PhotorealP2MotionNormalizationSelectionError(
                "P2 motion selected viewport is invalid for rectilinear source"
            )

        records.append(
            {
                "source_ref": ref,
                "source_key": universe["source_key"],
                "split": universe["split"],
                "role": universe["role"],
                "projection": universe["projection"],
                "stereo_layout": universe["stereo_layout"],
                "normalization_strategy": universe["normalization_strategy"],
                "selected_eye": eye,
                "selected_viewport_id": viewport,
                "human_selected": human_selected,
            }
        )

    records.sort(key=lambda item: item["source_ref"])
    result: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": plan["performer_id"],
        "selected_epoch_id": plan["selected_epoch_id"],
        "teacher_input_sha256": plan["teacher_input_sha256"],
        "p2_motion_input_plan_sha256": plan["p2_motion_input_plan_sha256"],
        "selections": records,
        "selection_count": len(records),
        "human_normalization_selection_required": human_required,
        "human_normalization_selection_complete": True,
        "reviewed_by": reviewer,
        "review_notes": review_notes.strip(),
        "source_media_rehash_performed": False,
        "p2_animation_execution_authorized": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    result["p2_motion_normalization_selection_sha256"] = _digest(
        result,
        omit="p2_motion_normalization_selection_sha256",
    )
    return validate_normalization_selection(result, input_plan=plan)


def validate_normalization_selection(
    value: Mapping[str, Any],
    *,
    input_plan: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_motion_input_plan_sha256",
        "selections",
        "selection_count",
        "human_normalization_selection_required",
        "human_normalization_selection_complete",
        "reviewed_by",
        "review_notes",
        "source_media_rehash_performed",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_motion_normalization_selection_sha256",
    }
    if set(value) != expected:
        raise PhotorealP2MotionNormalizationSelectionError(
            "P2 motion normalization selection fields must match v1 exactly"
        )
    if value.get("format") != FORMAT:
        raise PhotorealP2MotionNormalizationSelectionError(
            "P2 motion normalization selection format/version mismatch"
        )
    _strict_v1(value.get("version"), label="P2 motion normalization selection")
    for field in ("performer_id", "selected_epoch_id", "teacher_input_sha256", "p2_motion_input_plan_sha256"):
        if value.get(field) != input_plan.get(field):
            raise PhotorealP2MotionNormalizationSelectionError(
                f"P2 motion normalization selection lineage mismatch: {field}"
            )
    declared = _sha(
        value.get("p2_motion_normalization_selection_sha256"),
        label="P2 motion normalization selection SHA-256",
    )
    if _digest(value, omit="p2_motion_normalization_selection_sha256") != declared:
        raise PhotorealP2MotionNormalizationSelectionError(
            "P2 motion normalization selection digest mismatch"
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
        raise PhotorealP2MotionNormalizationSelectionError(
            "P2 motion normalization selection count mismatch"
        )
    expected_refs = {
        str(item["source_ref"])
        for item in list(input_plan["motion_driver_tasks"]) + list(input_plan["held_out_motion_validation_tasks"])
    }
    seen: set[str] = set()
    any_human = False
    for raw in selections:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionNormalizationSelectionError("P2 motion normalization record is invalid")
        fields = {
            "source_ref",
            "source_key",
            "split",
            "role",
            "projection",
            "stereo_layout",
            "normalization_strategy",
            "selected_eye",
            "selected_viewport_id",
            "human_selected",
        }
        if set(raw) != fields:
            raise PhotorealP2MotionNormalizationSelectionError(
                "P2 motion normalization record fields must match v1 exactly"
            )
        ref = _text(raw.get("source_ref"), label="P2 motion normalization source ref", maximum=64)
        if ref in seen or ref not in expected_refs:
            raise PhotorealP2MotionNormalizationSelectionError(
                "P2 motion normalization source universe mismatch"
            )
        seen.add(ref)
        if raw.get("selected_eye") not in {"mono", "left", "right"}:
            raise PhotorealP2MotionNormalizationSelectionError("P2 motion normalization selected eye is invalid")
        viewport = raw.get("selected_viewport_id")
        if viewport is not None:
            _text(viewport, label="P2 motion normalization selected viewport", maximum=64)
        if not isinstance(raw.get("human_selected"), bool):
            raise PhotorealP2MotionNormalizationSelectionError("P2 motion normalization human_selected is invalid")
        any_human = any_human or bool(raw["human_selected"])
    if seen != expected_refs:
        raise PhotorealP2MotionNormalizationSelectionError("P2 motion normalization omitted selected source")
    if value.get("human_normalization_selection_required") is not any_human:
        raise PhotorealP2MotionNormalizationSelectionError("P2 motion normalization human-selection flag mismatch")
    for field, expected_value in (
        ("human_normalization_selection_complete", True),
        ("source_media_rehash_performed", False),
        ("p2_animation_execution_authorized", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if value.get(field) is not expected_value:
            raise PhotorealP2MotionNormalizationSelectionError(
                f"P2 motion normalization authority mismatch: {field}"
            )
    _text(value.get("reviewed_by"), label="P2 motion normalization reviewer", maximum=256)
    notes = value.get("review_notes")
    if not isinstance(notes, str) or not notes.strip() or len(notes) > 8192:
        raise PhotorealP2MotionNormalizationSelectionError("P2 motion normalization review notes are invalid")
    return dict(value)
