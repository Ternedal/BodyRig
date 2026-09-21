from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .photoreal_p2_motion_window_selection import (
    PhotorealP2MotionWindowSelectionError,
    build_motion_window_selection,
    describe_motion_window_candidates,
    load_p0_artifacts,
)


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    source = path.expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealP2MotionWindowSelectionError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP2MotionWindowSelectionError(
            f"{label} must be a JSON object"
        )
    return value


def _parse_windows(values: list[str]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for raw in values:
        if "=" not in raw:
            raise PhotorealP2MotionWindowSelectionError(
                "motion window must use SOURCE_REF=OBSERVATION_REF,BEFORE_SECONDS,AFTER_SECONDS"
            )
        source_ref, payload = raw.split("=", 1)
        source_ref = source_ref.strip()
        parts = [item.strip() for item in payload.split(",")]
        if not source_ref or source_ref in result or len(parts) != 3:
            raise PhotorealP2MotionWindowSelectionError(
                "motion window source ref is empty/repeated or payload does not have three values"
            )
        observation_ref, before_raw, after_raw = parts
        if not observation_ref:
            raise PhotorealP2MotionWindowSelectionError(
                "motion window observation ref is empty"
            )
        try:
            before = float(before_raw)
            after = float(after_raw)
        except ValueError as exc:
            raise PhotorealP2MotionWindowSelectionError(
                "motion window before/after values must be numeric"
            ) from exc
        result[source_ref] = {
            "observation_ref": observation_ref,
            "before_seconds": before,
            "after_seconds": after,
        }
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Describe or record bounded P2 motion windows around strict P0 target observations."
    )
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--private-index", type=Path, required=True)
    parser.add_argument("--source-selection", type=Path, required=True)
    parser.add_argument("--input-plan", type=Path, required=True)
    parser.add_argument("--normalization-selection", type=Path, required=True)
    parser.add_argument("--p0-root", type=Path, required=True)
    parser.add_argument("--window", action="append", default=[])
    parser.add_argument("--reviewed-by", default="")
    parser.add_argument("--review-notes", default="")
    parser.add_argument("--approve-human-selection", action="store_true")
    parser.add_argument("--describe-only", action="store_true")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)

    try:
        handoff = _read_json(args.handoff, label="P2 motion evidence handoff")
        private_index = _read_json(args.private_index, label="private P2 motion source index")
        source_selection = _read_json(args.source_selection, label="P2 motion source selection")
        input_plan = _read_json(args.input_plan, label="P2 motion input plan")
        normalization = _read_json(
            args.normalization_selection,
            label="P2 motion normalization selection",
        )
        scan_plan, dataset_plan, source_receipt, authorized, frame_index = load_p0_artifacts(
            args.p0_root
        )

        if args.describe_only:
            candidates = describe_motion_window_candidates(
                handoff,
                private_index,
                source_selection,
                input_plan,
                normalization,
                scan_plan,
                dataset_plan,
                source_receipt,
                authorized,
                frame_index,
            )
            print(
                json.dumps(
                    {
                        "status": "P2_MOTION_WINDOW_CANDIDATES",
                        "maximum_total_window_seconds": 8.0,
                        "human_motion_window_selection_required": True,
                        "sources": candidates,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            return 2

        if args.out is None:
            raise PhotorealP2MotionWindowSelectionError(
                "--out is required unless --describe-only is used"
            )
        if not args.reviewed_by.strip() or not args.review_notes.strip():
            raise PhotorealP2MotionWindowSelectionError(
                "--reviewed-by and --review-notes are required when recording motion windows"
            )
        choices = _parse_windows(args.window)
        result = build_motion_window_selection(
            handoff,
            private_index,
            source_selection,
            input_plan,
            normalization,
            scan_plan,
            dataset_plan,
            source_receipt,
            authorized,
            frame_index,
            choices=choices,
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            approve_human_selection=args.approve_human_selection,
        )
        output = args.out.expanduser().resolve()
        if output.exists():
            if not args.reuse_existing:
                raise PhotorealP2MotionWindowSelectionError(
                    f"P2 motion window selection already exists: {output}"
                )
            existing = _read_json(output, label="existing P2 motion window selection")
            if existing != result:
                raise PhotorealP2MotionWindowSelectionError(
                    "existing P2 motion window selection differs from canonical current state"
                )
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
    except PhotorealP2MotionWindowSelectionError as exc:
        print(f"BodyRig P2 motion window selection: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P2_MOTION_WINDOWS_SELECTED",
                "selection_count": result["selection_count"],
                "maximum_total_window_seconds": result[
                    "maximum_total_window_seconds"
                ],
                "source_media_rehash_performed": False,
                "motion_input_preparation_execution_authorized": True,
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
