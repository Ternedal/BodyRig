from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping

from .photoreal_p2_motion_evidence import (
    PhotorealP2MotionEvidenceError,
    validate_motion_evidence_handoff,
    validate_private_motion_index,
)
from .photoreal_p2_motion_selection import (
    PhotorealP2MotionSelectionError,
    validate_motion_source_selection,
)


FORMAT = "bodyrig-photoreal-p2-motion-input-plan"
VERSION = 1


class PhotorealP2MotionInputPlanError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2MotionInputPlanError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealP2MotionInputPlanError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 32768) -> str:
    if not isinstance(value, str):
        raise PhotorealP2MotionInputPlanError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2MotionInputPlanError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealP2MotionInputPlanError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2MotionInputPlanError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2MotionInputPlanError(f"{label} format/version mismatch")


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
        raise PhotorealP2MotionInputPlanError("P2 motion input plan cannot be canonically serialized") from exc
    return hashlib.sha256(raw).hexdigest()


def _private_entry_map(private_index: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    raw_entries = private_index.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise PhotorealP2MotionInputPlanError("private P2 motion index contains no source entries")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in raw_entries:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionInputPlanError("private P2 motion index entry is invalid")
        source_ref = _text(raw.get("source_ref"), label="private P2 motion source ref", maximum=64)
        if source_ref in result:
            raise PhotorealP2MotionInputPlanError("private P2 motion index repeats source ref")
        result[source_ref] = raw
    return result


def _task(
    selected: Mapping[str, Any],
    private: Mapping[str, Any],
    *,
    expected_split: str,
    role: str,
) -> dict[str, Any]:
    source_ref = _text(selected.get("source_ref"), label="selected P2 source ref", maximum=64)
    if private.get("source_ref") != source_ref:
        raise PhotorealP2MotionInputPlanError("selected/private P2 source reference mismatch")
    for field in ("group_ref", "split", "source_sha256"):
        if private.get(field) != selected.get(field):
            raise PhotorealP2MotionInputPlanError(f"selected/private P2 source binding mismatch: {field}")
    if selected.get("split") != expected_split:
        raise PhotorealP2MotionInputPlanError("selected P2 source split mismatch")

    preparation_mode = _text(
        selected.get("preparation_mode"),
        label="selected P2 preparation mode",
        maximum=128,
    )
    if preparation_mode == "direct-exavatar-video":
        normalization_action = "preserve-flat-mono-video"
    elif preparation_mode == "exact-authorized-deprojection-required":
        normalization_action = "exact-authorized-deprojection"
    else:
        raise PhotorealP2MotionInputPlanError("selected P2 preparation mode is unsupported")

    size = private.get("size_bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise PhotorealP2MotionInputPlanError("private selected P2 source size is invalid")

    return {
        "source_ref": source_ref,
        "group_ref": _text(selected.get("group_ref"), label="selected P2 group ref", maximum=64),
        "split": expected_split,
        "role": role,
        "source_key": _text(private.get("source_key"), label="private selected P2 source key"),
        "group_id": _text(private.get("group_id"), label="private selected P2 group id"),
        "resolved_path": _text(private.get("resolved_path"), label="private selected P2 source path"),
        "source_sha256": _sha(selected.get("source_sha256"), label="selected P2 source SHA-256"),
        "size_bytes": size,
        "preparation_mode": preparation_mode,
        "normalization_action": normalization_action,
        "motion_parameter_extraction_required": True,
        "source_media_rehash_required": False,
        "preparation_complete": False,
    }


def build_motion_input_plan(
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        validated_handoff = validate_motion_evidence_handoff(handoff)
        validated_private = validate_private_motion_index(
            private_index,
            handoff=validated_handoff,
        )
        validated_selection = validate_motion_source_selection(
            selection,
            handoff=validated_handoff,
            private_index=validated_private,
        )
    except (PhotorealP2MotionEvidenceError, PhotorealP2MotionSelectionError) as exc:
        raise PhotorealP2MotionInputPlanError(f"P2 motion input authority readback failed: {exc}") from exc

    if validated_selection.get("p2_motion_input_authorized") is not True:
        raise PhotorealP2MotionInputPlanError("P2 motion source selection did not authorize input preparation")
    if validated_selection.get("p2_animation_execution_authorized") is not False:
        raise PhotorealP2MotionInputPlanError("P2 motion selection unexpectedly authorized animation execution")

    private_by_ref = _private_entry_map(validated_private)

    drivers_raw = validated_selection.get("motion_driver_sources")
    heldout_raw = validated_selection.get("held_out_motion_validation_sources")
    if not isinstance(drivers_raw, list) or not drivers_raw:
        raise PhotorealP2MotionInputPlanError("P2 motion selection contains no driver sources")
    if not isinstance(heldout_raw, list) or not heldout_raw:
        raise PhotorealP2MotionInputPlanError("P2 motion selection contains no held-out validation sources")

    driver_tasks: list[dict[str, Any]] = []
    validation_tasks: list[dict[str, Any]] = []
    selected_refs: set[str] = set()

    for selected in drivers_raw:
        if not isinstance(selected, Mapping):
            raise PhotorealP2MotionInputPlanError("selected P2 motion driver is invalid")
        source_ref = _text(selected.get("source_ref"), label="selected driver source ref", maximum=64)
        if source_ref in selected_refs or source_ref not in private_by_ref:
            raise PhotorealP2MotionInputPlanError("selected P2 driver source universe mismatch")
        selected_refs.add(source_ref)
        driver_tasks.append(
            _task(
                selected,
                private_by_ref[source_ref],
                expected_split="train",
                role="motion-driver",
            )
        )

    for selected in heldout_raw:
        if not isinstance(selected, Mapping):
            raise PhotorealP2MotionInputPlanError("selected P2 held-out source is invalid")
        source_ref = _text(selected.get("source_ref"), label="selected held-out source ref", maximum=64)
        if source_ref in selected_refs or source_ref not in private_by_ref:
            raise PhotorealP2MotionInputPlanError("selected P2 held-out source universe mismatch")
        selected_refs.add(source_ref)
        validation_tasks.append(
            _task(
                selected,
                private_by_ref[source_ref],
                expected_split="evaluation",
                role="held-out-motion-validation",
            )
        )

    driver_tasks.sort(key=lambda item: item["source_ref"])
    validation_tasks.sort(key=lambda item: item["source_ref"])
    all_tasks = driver_tasks + validation_tasks

    plan: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": _text(validated_selection.get("performer_id"), label="P2 motion performer", maximum=256),
        "selected_epoch_id": _text(validated_selection.get("selected_epoch_id"), label="P2 motion epoch", maximum=256),
        "teacher_input_sha256": _sha(validated_selection.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "p2_animation_plan_sha256": _sha(
            validated_selection.get("p2_animation_plan_sha256"),
            label="P2 animation plan SHA-256",
        ),
        "p2_motion_evidence_handoff_sha256": _sha(
            validated_selection.get("p2_motion_evidence_handoff_sha256"),
            label="P2 motion evidence handoff SHA-256",
        ),
        "p2_motion_private_index_sha256": _sha(
            validated_selection.get("p2_motion_private_index_sha256"),
            label="P2 private motion index SHA-256",
        ),
        "p2_motion_source_selection_sha256": _sha(
            validated_selection.get("p2_motion_source_selection_sha256"),
            label="P2 motion source selection SHA-256",
        ),
        "motion_driver_tasks": driver_tasks,
        "held_out_motion_validation_tasks": validation_tasks,
        "motion_driver_task_count": len(driver_tasks),
        "held_out_motion_validation_task_count": len(validation_tasks),
        "exact_deprojection_task_count": sum(
            1 for item in all_tasks if item["normalization_action"] == "exact-authorized-deprojection"
        ),
        "direct_flat_mono_task_count": sum(
            1 for item in all_tasks if item["normalization_action"] == "preserve-flat-mono-video"
        ),
        "build_private": True,
        "source_media_rehash_required": False,
        "source_media_rehash_performed": False,
        "motion_parameter_extraction_required": True,
        "motion_fitting_backend": "pinned-exavatar-fitting-v1",
        "motion_fitting_camera_mode": "virtual",
        "motion_input_plan_ready": True,
        "p2_motion_input_authorized": True,
        "motion_input_preparation_execution_authorized": False,
        "p2_animation_execution_authorized": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    plan["p2_motion_input_plan_sha256"] = _digest(
        plan,
        omit="p2_motion_input_plan_sha256",
    )
    return validate_motion_input_plan(
        plan,
        handoff=validated_handoff,
        private_index=validated_private,
        selection=validated_selection,
    )


def _validate_tasks(
    values: Any,
    *,
    expected_split: str,
    expected_role: str,
    private_by_ref: Mapping[str, Mapping[str, Any]],
    selected_by_ref: Mapping[str, Mapping[str, Any]],
    label: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list) or not values:
        raise PhotorealP2MotionInputPlanError(f"{label} is invalid")
    expected_fields = {
        "source_ref",
        "group_ref",
        "split",
        "role",
        "source_key",
        "group_id",
        "resolved_path",
        "source_sha256",
        "size_bytes",
        "preparation_mode",
        "normalization_action",
        "motion_parameter_extraction_required",
        "source_media_rehash_required",
        "preparation_complete",
    }
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping) or set(raw) != expected_fields:
            raise PhotorealP2MotionInputPlanError(f"{label} fields must match v1 exactly")
        source_ref = _text(raw.get("source_ref"), label=f"{label} source ref", maximum=64)
        if source_ref in result or source_ref not in private_by_ref or source_ref not in selected_by_ref:
            raise PhotorealP2MotionInputPlanError(f"{label} source universe mismatch")
        if raw.get("split") != expected_split or raw.get("role") != expected_role:
            raise PhotorealP2MotionInputPlanError(f"{label} split/role mismatch")

        selected = selected_by_ref[source_ref]
        private = private_by_ref[source_ref]
        for field in ("group_ref", "split", "source_sha256", "preparation_mode"):
            if raw.get(field) != selected.get(field):
                raise PhotorealP2MotionInputPlanError(f"{label} selection binding mismatch: {field}")
        for field in ("source_key", "group_id", "resolved_path", "size_bytes"):
            if raw.get(field) != private.get(field):
                raise PhotorealP2MotionInputPlanError(f"{label} private binding mismatch: {field}")

        if raw.get("preparation_mode") == "direct-exavatar-video":
            expected_action = "preserve-flat-mono-video"
        elif raw.get("preparation_mode") == "exact-authorized-deprojection-required":
            expected_action = "exact-authorized-deprojection"
        else:
            raise PhotorealP2MotionInputPlanError(f"{label} preparation mode is unsupported")
        if raw.get("normalization_action") != expected_action:
            raise PhotorealP2MotionInputPlanError(f"{label} normalization action mismatch")
        for field, expected in (
            ("motion_parameter_extraction_required", True),
            ("source_media_rehash_required", False),
            ("preparation_complete", False),
        ):
            if raw.get(field) is not expected:
                raise PhotorealP2MotionInputPlanError(f"{label} authority mismatch: {field}")
        result[source_ref] = dict(raw)
    return result


def validate_motion_input_plan(
    plan: Mapping[str, Any],
    *,
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
    selection: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        validated_handoff = validate_motion_evidence_handoff(handoff)
        validated_private = validate_private_motion_index(
            private_index,
            handoff=validated_handoff,
        )
        validated_selection = validate_motion_source_selection(
            selection,
            handoff=validated_handoff,
            private_index=validated_private,
        )
    except (PhotorealP2MotionEvidenceError, PhotorealP2MotionSelectionError) as exc:
        raise PhotorealP2MotionInputPlanError(f"P2 motion input authority readback failed: {exc}") from exc

    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_motion_evidence_handoff_sha256",
        "p2_motion_private_index_sha256",
        "p2_motion_source_selection_sha256",
        "motion_driver_tasks",
        "held_out_motion_validation_tasks",
        "motion_driver_task_count",
        "held_out_motion_validation_task_count",
        "exact_deprojection_task_count",
        "direct_flat_mono_task_count",
        "build_private",
        "source_media_rehash_required",
        "source_media_rehash_performed",
        "motion_parameter_extraction_required",
        "motion_fitting_backend",
        "motion_fitting_camera_mode",
        "motion_input_plan_ready",
        "p2_motion_input_authorized",
        "motion_input_preparation_execution_authorized",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_motion_input_plan_sha256",
    }
    if set(plan) != expected_fields:
        raise PhotorealP2MotionInputPlanError("P2 motion input plan fields must match v1 exactly")
    if plan.get("format") != FORMAT:
        raise PhotorealP2MotionInputPlanError("P2 motion input plan format/version mismatch")
    _strict_v1(plan.get("version"), label="P2 motion input plan")
    claimed = _sha(plan.get("p2_motion_input_plan_sha256"), label="P2 motion input plan SHA-256")
    if _digest(plan, omit="p2_motion_input_plan_sha256") != claimed:
        raise PhotorealP2MotionInputPlanError("P2 motion input plan digest mismatch")

    lineage = {
        "performer_id": "performer_id",
        "selected_epoch_id": "selected_epoch_id",
        "teacher_input_sha256": "teacher_input_sha256",
        "p2_animation_plan_sha256": "p2_animation_plan_sha256",
        "p2_motion_evidence_handoff_sha256": "p2_motion_evidence_handoff_sha256",
        "p2_motion_private_index_sha256": "p2_motion_private_index_sha256",
        "p2_motion_source_selection_sha256": "p2_motion_source_selection_sha256",
    }
    for plan_field, selection_field in lineage.items():
        if plan.get(plan_field) != validated_selection.get(selection_field):
            raise PhotorealP2MotionInputPlanError(f"P2 motion input plan lineage mismatch: {plan_field}")

    private_by_ref = _private_entry_map(validated_private)
    drivers_raw = validated_selection.get("motion_driver_sources")
    heldout_raw = validated_selection.get("held_out_motion_validation_sources")
    if not isinstance(drivers_raw, list) or not isinstance(heldout_raw, list):
        raise PhotorealP2MotionInputPlanError("P2 motion selection source lists are invalid")
    drivers = {
        _text(item.get("source_ref"), label="selected driver source ref", maximum=64): item
        for item in drivers_raw
        if isinstance(item, Mapping)
    }
    heldout = {
        _text(item.get("source_ref"), label="selected held-out source ref", maximum=64): item
        for item in heldout_raw
        if isinstance(item, Mapping)
    }

    driver_tasks = _validate_tasks(
        plan.get("motion_driver_tasks"),
        expected_split="train",
        expected_role="motion-driver",
        private_by_ref=private_by_ref,
        selected_by_ref=drivers,
        label="P2 motion driver tasks",
    )
    validation_tasks = _validate_tasks(
        plan.get("held_out_motion_validation_tasks"),
        expected_split="evaluation",
        expected_role="held-out-motion-validation",
        private_by_ref=private_by_ref,
        selected_by_ref=heldout,
        label="P2 held-out validation tasks",
    )
    if set(driver_tasks) != set(drivers):
        raise PhotorealP2MotionInputPlanError("P2 motion input plan omitted/added driver sources")
    if set(validation_tasks) != set(heldout):
        raise PhotorealP2MotionInputPlanError("P2 motion input plan omitted/added held-out sources")
    if set(driver_tasks) & set(validation_tasks):
        raise PhotorealP2MotionInputPlanError("P2 motion input plan crosses train/evaluation source boundary")

    all_tasks = list(driver_tasks.values()) + list(validation_tasks.values())
    if plan.get("motion_driver_task_count") != len(driver_tasks):
        raise PhotorealP2MotionInputPlanError("P2 motion input driver task count mismatch")
    if plan.get("held_out_motion_validation_task_count") != len(validation_tasks):
        raise PhotorealP2MotionInputPlanError("P2 motion input held-out task count mismatch")
    expected_deprojection = sum(
        1 for item in all_tasks if item["normalization_action"] == "exact-authorized-deprojection"
    )
    expected_direct = sum(
        1 for item in all_tasks if item["normalization_action"] == "preserve-flat-mono-video"
    )
    if plan.get("exact_deprojection_task_count") != expected_deprojection:
        raise PhotorealP2MotionInputPlanError("P2 motion input deprojection task count mismatch")
    if plan.get("direct_flat_mono_task_count") != expected_direct:
        raise PhotorealP2MotionInputPlanError("P2 motion input direct task count mismatch")

    if plan.get("motion_fitting_backend") != "pinned-exavatar-fitting-v1":
        raise PhotorealP2MotionInputPlanError("P2 motion fitting backend mismatch")
    if plan.get("motion_fitting_camera_mode") != "virtual":
        raise PhotorealP2MotionInputPlanError("P2 motion fitting camera mode mismatch")

    for field, expected in (
        ("build_private", True),
        ("source_media_rehash_required", False),
        ("source_media_rehash_performed", False),
        ("motion_parameter_extraction_required", True),
        ("motion_input_plan_ready", True),
        ("p2_motion_input_authorized", True),
        ("motion_input_preparation_execution_authorized", False),
        ("p2_animation_execution_authorized", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if plan.get(field) is not expected:
            raise PhotorealP2MotionInputPlanError(f"P2 motion input plan authority mismatch: {field}")
    return dict(plan)


def build_motion_input_plan_files(
    handoff_path: str | Path,
    private_index_path: str | Path,
    selection_path: str | Path,
    output_path: str | Path,
    *,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    handoff = _read_json(handoff_path, label="P2 motion evidence handoff")
    private_index = _read_json(private_index_path, label="private P2 motion source index")
    selection = _read_json(selection_path, label="P2 motion source selection")
    plan = build_motion_input_plan(handoff, private_index, selection)

    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP2MotionInputPlanError(f"P2 motion input plan already exists: {output}")
        existing = _read_json(output, label="existing P2 motion input plan")
        if existing != plan:
            raise PhotorealP2MotionInputPlanError(
                f"existing P2 motion input plan differs from canonical current state: {output}"
            )
        return plan
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(plan, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        raise PhotorealP2MotionInputPlanError(f"failed to persist P2 motion input plan: {output}") from exc
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the private, non-executing P2 motion-input preparation plan."
    )
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--private-index", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        plan = build_motion_input_plan_files(
            args.handoff,
            args.private_index,
            args.selection,
            args.out,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP2MotionInputPlanError as exc:
        print(f"BodyRig P2 motion input plan: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P2_MOTION_INPUT_PLAN_READY",
                "motion_driver_task_count": plan["motion_driver_task_count"],
                "held_out_motion_validation_task_count": plan[
                    "held_out_motion_validation_task_count"
                ],
                "exact_deprojection_task_count": plan["exact_deprojection_task_count"],
                "source_media_rehash_required": False,
                "motion_input_preparation_execution_authorized": False,
                "p2_animation_execution_authorized": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
