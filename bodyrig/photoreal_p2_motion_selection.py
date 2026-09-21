from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from .photoreal_p2_motion_evidence import (
    PhotorealP2MotionEvidenceError,
    validate_motion_evidence_handoff,
    validate_private_motion_index,
)


FORMAT = "bodyrig-photoreal-p2-motion-source-selection"
VERSION = 1


class PhotorealP2MotionSelectionError(ValueError):
    pass


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(
            source.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealP2MotionSelectionError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealP2MotionSelectionError(f"{label} must be a JSON object")
    return value


def _text(value: Any, *, label: str, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        raise PhotorealP2MotionSelectionError(f"{label} is invalid")
    result = value.strip()
    if not result or len(value) > maximum or "\n" in result or "\r" in result:
        raise PhotorealP2MotionSelectionError(f"{label} is invalid")
    return result


def _sha(value: Any, *, label: str) -> str:
    result = _text(value, label=label, maximum=64).lower()
    if len(result) != 64 or any(character not in "0123456789abcdef" for character in result):
        raise PhotorealP2MotionSelectionError(f"{label} is invalid")
    return result


def _strict_v1(value: Any, *, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PhotorealP2MotionSelectionError(f"{label} format/version mismatch")
    number = float(value)
    if not math.isfinite(number) or number != 1.0:
        raise PhotorealP2MotionSelectionError(f"{label} format/version mismatch")


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
        raise PhotorealP2MotionSelectionError("P2 motion selection cannot be canonically serialized") from exc
    return hashlib.sha256(raw).hexdigest()


def _normalized_refs(values: Sequence[str], *, label: str) -> list[str]:
    result = [_text(value, label=label, maximum=64) for value in values]
    if not result:
        raise PhotorealP2MotionSelectionError(f"{label} requires at least one source ref")
    if len(result) != len(set(result)):
        raise PhotorealP2MotionSelectionError(f"{label} repeats source ref")
    return sorted(result)


def _public_candidate_map(values: Any, *, label: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(values, list) or not values:
        raise PhotorealP2MotionSelectionError(f"{label} is invalid")
    result: dict[str, Mapping[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping):
            raise PhotorealP2MotionSelectionError(f"{label} entry is invalid")
        ref = _text(raw.get("source_ref"), label=f"{label} source ref", maximum=64)
        if ref in result:
            raise PhotorealP2MotionSelectionError(f"{label} repeats source ref")
        result[ref] = raw
    return result


def build_motion_source_selection(
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
    *,
    motion_driver_source_refs: Sequence[str],
    held_out_validation_source_refs: Sequence[str],
    reviewed_by: str,
    review_notes: str,
    approve_human_selection: bool,
) -> dict[str, Any]:
    if approve_human_selection is not True:
        raise PhotorealP2MotionSelectionError("P2 motion source selection requires explicit human approval")
    try:
        validated_handoff = validate_motion_evidence_handoff(handoff)
        validated_private = validate_private_motion_index(
            private_index,
            handoff=validated_handoff,
        )
    except PhotorealP2MotionEvidenceError as exc:
        raise PhotorealP2MotionSelectionError(f"P2 motion handoff strict readback failed: {exc}") from exc

    driver_refs = _normalized_refs(
        motion_driver_source_refs,
        label="P2 motion driver selection",
    )
    validation_refs = _normalized_refs(
        held_out_validation_source_refs,
        label="P2 held-out validation selection",
    )
    if set(driver_refs) & set(validation_refs):
        raise PhotorealP2MotionSelectionError("P2 motion driver/validation selections overlap")

    drivers = _public_candidate_map(
        validated_handoff.get("motion_driver_candidates"),
        label="P2 motion driver candidates",
    )
    heldout = _public_candidate_map(
        validated_handoff.get("held_out_motion_validation_candidates"),
        label="P2 held-out motion candidates",
    )
    unknown_drivers = sorted(set(driver_refs) - set(drivers))
    unknown_validation = sorted(set(validation_refs) - set(heldout))
    if unknown_drivers:
        raise PhotorealP2MotionSelectionError("P2 motion driver selection is outside TRAIN candidates")
    if unknown_validation:
        raise PhotorealP2MotionSelectionError("P2 validation selection is outside HELD-OUT EVALUATION candidates")

    driver_groups = {drivers[ref]["group_ref"] for ref in driver_refs}
    validation_groups = {heldout[ref]["group_ref"] for ref in validation_refs}
    if driver_groups & validation_groups:
        raise PhotorealP2MotionSelectionError("P2 motion selection source groups overlap train/evaluation")

    reviewer = _text(reviewed_by, label="P2 motion selection reviewer", maximum=256)
    if not isinstance(review_notes, str) or not review_notes.strip() or len(review_notes) > 8192:
        raise PhotorealP2MotionSelectionError("P2 motion selection review notes are invalid")

    def selected_record(candidate: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "source_ref": _text(candidate.get("source_ref"), label="selected P2 source ref", maximum=64),
            "group_ref": _text(candidate.get("group_ref"), label="selected P2 group ref", maximum=64),
            "split": _text(candidate.get("split"), label="selected P2 split", maximum=16),
            "source_sha256": _sha(candidate.get("source_sha256"), label="selected P2 source SHA-256"),
            "preparation_mode": _text(
                candidate.get("preparation_mode"),
                label="selected P2 preparation mode",
                maximum=128,
            ),
        }

    receipt: dict[str, Any] = {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": _text(validated_handoff.get("performer_id"), label="P2 motion performer", maximum=256),
        "selected_epoch_id": _text(validated_handoff.get("selected_epoch_id"), label="P2 motion epoch", maximum=256),
        "teacher_input_sha256": _sha(validated_handoff.get("teacher_input_sha256"), label="teacher input SHA-256"),
        "p2_animation_plan_sha256": _sha(
            validated_handoff.get("p2_animation_plan_sha256"),
            label="P2 animation plan SHA-256",
        ),
        "p2_motion_evidence_handoff_sha256": _sha(
            validated_handoff.get("p2_motion_evidence_handoff_sha256"),
            label="P2 motion handoff SHA-256",
        ),
        "p2_motion_private_index_sha256": _sha(
            validated_private.get("p2_motion_private_index_sha256"),
            label="private P2 motion index SHA-256",
        ),
        "motion_driver_sources": [selected_record(drivers[ref]) for ref in driver_refs],
        "held_out_motion_validation_sources": [selected_record(heldout[ref]) for ref in validation_refs],
        "motion_driver_source_count": len(driver_refs),
        "held_out_motion_validation_source_count": len(validation_refs),
        "reviewed_by": reviewer,
        "review_notes": review_notes.strip(),
        "source_media_rehash_required": False,
        "source_media_rehash_performed": False,
        "human_motion_source_selection_required": True,
        "human_motion_source_selection_complete": True,
        "motion_source_selection_authority": True,
        "p2_motion_input_authorized": True,
        "p2_animation_execution_authorized": False,
        "p2_animated_teacher_acceptance_authority": False,
        "quest_distillation_authorized": False,
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    receipt["p2_motion_source_selection_sha256"] = _digest(
        receipt,
        omit="p2_motion_source_selection_sha256",
    )
    return validate_motion_source_selection(
        receipt,
        handoff=validated_handoff,
        private_index=validated_private,
    )


def _validate_selected_sources(
    values: Any,
    *,
    expected_split: str,
    candidates: Mapping[str, Mapping[str, Any]],
    label: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(values, list) or not values:
        raise PhotorealP2MotionSelectionError(f"{label} is invalid")
    expected_fields = {
        "source_ref",
        "group_ref",
        "split",
        "source_sha256",
        "preparation_mode",
    }
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if not isinstance(raw, Mapping) or set(raw) != expected_fields:
            raise PhotorealP2MotionSelectionError(f"{label} fields must match v1 exactly")
        ref = _text(raw.get("source_ref"), label=f"{label} source ref", maximum=64)
        if ref in result or ref not in candidates:
            raise PhotorealP2MotionSelectionError(f"{label} source universe mismatch")
        candidate = candidates[ref]
        if raw.get("split") != expected_split:
            raise PhotorealP2MotionSelectionError(f"{label} split mismatch")
        for field in ("group_ref", "source_sha256", "preparation_mode"):
            if raw.get(field) != candidate.get(field):
                raise PhotorealP2MotionSelectionError(f"{label} candidate binding mismatch: {field}")
        result[ref] = dict(raw)
    return result


def validate_motion_source_selection(
    receipt: Mapping[str, Any],
    *,
    handoff: Mapping[str, Any],
    private_index: Mapping[str, Any],
) -> dict[str, Any]:
    try:
        validated_handoff = validate_motion_evidence_handoff(handoff)
        validated_private = validate_private_motion_index(
            private_index,
            handoff=validated_handoff,
        )
    except PhotorealP2MotionEvidenceError as exc:
        raise PhotorealP2MotionSelectionError(f"P2 motion handoff strict readback failed: {exc}") from exc

    expected_fields = {
        "format",
        "version",
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_motion_evidence_handoff_sha256",
        "p2_motion_private_index_sha256",
        "motion_driver_sources",
        "held_out_motion_validation_sources",
        "motion_driver_source_count",
        "held_out_motion_validation_source_count",
        "reviewed_by",
        "review_notes",
        "source_media_rehash_required",
        "source_media_rehash_performed",
        "human_motion_source_selection_required",
        "human_motion_source_selection_complete",
        "motion_source_selection_authority",
        "p2_motion_input_authorized",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
        "p2_motion_source_selection_sha256",
    }
    if set(receipt) != expected_fields:
        raise PhotorealP2MotionSelectionError("P2 motion selection fields must match v1 exactly")
    if receipt.get("format") != FORMAT:
        raise PhotorealP2MotionSelectionError("P2 motion selection format/version mismatch")
    _strict_v1(receipt.get("version"), label="P2 motion selection")
    claimed = _sha(
        receipt.get("p2_motion_source_selection_sha256"),
        label="P2 motion selection SHA-256",
    )
    if _digest(receipt, omit="p2_motion_source_selection_sha256") != claimed:
        raise PhotorealP2MotionSelectionError("P2 motion selection digest mismatch")

    for field in (
        "performer_id",
        "selected_epoch_id",
        "teacher_input_sha256",
        "p2_animation_plan_sha256",
        "p2_motion_evidence_handoff_sha256",
    ):
        if receipt.get(field) != validated_handoff.get(field):
            raise PhotorealP2MotionSelectionError(f"P2 motion selection handoff provenance mismatch: {field}")
    if receipt.get("p2_motion_private_index_sha256") != validated_private.get("p2_motion_private_index_sha256"):
        raise PhotorealP2MotionSelectionError("P2 motion selection private-index provenance mismatch")

    drivers = _public_candidate_map(
        validated_handoff.get("motion_driver_candidates"),
        label="P2 motion driver candidates",
    )
    heldout = _public_candidate_map(
        validated_handoff.get("held_out_motion_validation_candidates"),
        label="P2 held-out motion candidates",
    )
    selected_drivers = _validate_selected_sources(
        receipt.get("motion_driver_sources"),
        expected_split="train",
        candidates=drivers,
        label="P2 selected motion drivers",
    )
    selected_heldout = _validate_selected_sources(
        receipt.get("held_out_motion_validation_sources"),
        expected_split="evaluation",
        candidates=heldout,
        label="P2 selected held-out validation sources",
    )
    if set(selected_drivers) & set(selected_heldout):
        raise PhotorealP2MotionSelectionError("P2 selected motion source refs overlap")
    if receipt.get("motion_driver_source_count") != len(selected_drivers):
        raise PhotorealP2MotionSelectionError("P2 motion driver selection count mismatch")
    if receipt.get("held_out_motion_validation_source_count") != len(selected_heldout):
        raise PhotorealP2MotionSelectionError("P2 held-out motion selection count mismatch")

    _text(receipt.get("reviewed_by"), label="P2 motion selection reviewer", maximum=256)
    notes = receipt.get("review_notes")
    if not isinstance(notes, str) or not notes.strip() or len(notes) > 8192:
        raise PhotorealP2MotionSelectionError("P2 motion selection review notes are invalid")
    for field, expected in (
        ("source_media_rehash_required", False),
        ("source_media_rehash_performed", False),
        ("human_motion_source_selection_required", True),
        ("human_motion_source_selection_complete", True),
        ("motion_source_selection_authority", True),
        ("p2_motion_input_authorized", True),
        ("p2_animation_execution_authorized", False),
        ("p2_animated_teacher_acceptance_authority", False),
        ("quest_distillation_authorized", False),
        ("photoreal_acceptance_authority", False),
        ("production_activation", False),
    ):
        if receipt.get(field) is not expected:
            raise PhotorealP2MotionSelectionError(f"P2 motion selection authority mismatch: {field}")
    return dict(receipt)


def record_motion_source_selection_files(
    handoff_path: str | Path,
    private_index_path: str | Path,
    output_path: str | Path,
    *,
    motion_driver_source_refs: Sequence[str],
    held_out_validation_source_refs: Sequence[str],
    reviewed_by: str,
    review_notes: str,
    approve_human_selection: bool,
    reuse_existing: bool = False,
) -> dict[str, Any]:
    handoff = _read_json(handoff_path, label="P2 motion evidence handoff")
    private_index = _read_json(private_index_path, label="private P2 motion source index")
    receipt = build_motion_source_selection(
        handoff,
        private_index,
        motion_driver_source_refs=motion_driver_source_refs,
        held_out_validation_source_refs=held_out_validation_source_refs,
        reviewed_by=reviewed_by,
        review_notes=review_notes,
        approve_human_selection=approve_human_selection,
    )
    output = Path(output_path).expanduser().resolve()
    if output.exists():
        if not reuse_existing:
            raise PhotorealP2MotionSelectionError(f"P2 motion source selection already exists: {output}")
        existing = _read_json(output, label="existing P2 motion source selection")
        if existing != receipt:
            raise PhotorealP2MotionSelectionError(
                f"existing P2 motion source selection differs from canonical current state: {output}"
            )
        return receipt
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(receipt, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
    except OSError as exc:
        raise PhotorealP2MotionSelectionError(f"failed to persist P2 motion source selection: {output}") from exc
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record explicit human P2 motion-driver and held-out validation source selection."
    )
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--private-index", type=Path, required=True)
    parser.add_argument("--motion-driver-source-ref", action="append", default=[])
    parser.add_argument("--held-out-validation-source-ref", action="append", default=[])
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--review-notes", required=True)
    parser.add_argument("--approve-human-selection", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)
    try:
        receipt = record_motion_source_selection_files(
            args.handoff,
            args.private_index,
            args.out,
            motion_driver_source_refs=args.motion_driver_source_ref,
            held_out_validation_source_refs=args.held_out_validation_source_ref,
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            approve_human_selection=args.approve_human_selection,
            reuse_existing=args.reuse_existing,
        )
    except PhotorealP2MotionSelectionError as exc:
        print(f"BodyRig P2 motion source selection: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P2_MOTION_INPUT_PREPARATION_AUTHORIZED",
                "motion_driver_source_count": receipt["motion_driver_source_count"],
                "held_out_motion_validation_source_count": receipt[
                    "held_out_motion_validation_source_count"
                ],
                "source_media_rehash_required": False,
                "p2_motion_input_authorized": True,
                "p2_animation_execution_authorized": False,
                "p2_animated_teacher_acceptance_authority": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
