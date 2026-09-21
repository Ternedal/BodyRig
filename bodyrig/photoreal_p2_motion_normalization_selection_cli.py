from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .photoreal_p2_motion_normalization_selection import (
    PhotorealP2MotionNormalizationSelectionError,
    build_normalization_selection,
)


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    source = path.expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealP2MotionNormalizationSelectionError(
            f"{label} is unreadable: {source}"
        ) from exc
    if not isinstance(value, dict):
        raise PhotorealP2MotionNormalizationSelectionError(
            f"{label} must be a JSON object"
        )
    return value


def _parse_choices(values: list[str]) -> dict[str, dict[str, str | None]]:
    result: dict[str, dict[str, str | None]] = {}
    for raw in values:
        if "=" not in raw:
            raise PhotorealP2MotionNormalizationSelectionError(
                "normalization choice must use SOURCE_REF=EYE or SOURCE_REF=EYE@VIEWPORT"
            )
        source_ref, raw_value = raw.split("=", 1)
        source_ref = source_ref.strip()
        raw_value = raw_value.strip()
        if not source_ref or not raw_value or source_ref in result:
            raise PhotorealP2MotionNormalizationSelectionError(
                "normalization choice source ref is empty or repeated"
            )
        if "@" in raw_value:
            eye, viewport = raw_value.split("@", 1)
            eye = eye.strip()
            viewport = viewport.strip()
            if not viewport:
                raise PhotorealP2MotionNormalizationSelectionError(
                    "normalization viewport is empty"
                )
        else:
            eye = raw_value.strip()
            viewport = None
        if eye not in {"mono", "left", "right"}:
            raise PhotorealP2MotionNormalizationSelectionError(
                f"normalization eye is invalid: {eye}"
            )
        result[source_ref] = {"eye": eye, "viewport_id": viewport}
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record explicit P2 motion eye/viewport normalization authority."
    )
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--private-index", type=Path, required=True)
    parser.add_argument("--source-selection", type=Path, required=True)
    parser.add_argument("--input-plan", type=Path, required=True)
    parser.add_argument("--scan-plan", type=Path, required=True)
    parser.add_argument("--choice", action="append", default=[])
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--review-notes", required=True)
    parser.add_argument("--approve-human-selection", action="store_true")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    args = parser.parse_args(argv)

    try:
        choices = _parse_choices(args.choice)
        result = build_normalization_selection(
            _read_json(args.handoff, label="P2 motion evidence handoff"),
            _read_json(args.private_index, label="private P2 motion source index"),
            _read_json(args.source_selection, label="P2 motion source selection"),
            _read_json(args.input_plan, label="P2 motion input plan"),
            _read_json(args.scan_plan, label="P0 scan plan"),
            choices=choices or None,
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            approve_human_selection=args.approve_human_selection,
        )
        output = args.out.expanduser().resolve()
        if output.exists():
            if not args.reuse_existing:
                raise PhotorealP2MotionNormalizationSelectionError(
                    f"P2 motion normalization selection already exists: {output}"
                )
            existing = _read_json(output, label="existing P2 motion normalization selection")
            if existing != result:
                raise PhotorealP2MotionNormalizationSelectionError(
                    "existing P2 motion normalization selection differs from canonical current state"
                )
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
                stream.write("\n")
    except PhotorealP2MotionNormalizationSelectionError as exc:
        print(f"BodyRig P2 motion normalization selection: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P2_MOTION_NORMALIZATION_SELECTED",
                "selection_count": result["selection_count"],
                "human_normalization_selection_required": result[
                    "human_normalization_selection_required"
                ],
                "human_normalization_selection_complete": True,
                "source_media_rehash_performed": False,
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
