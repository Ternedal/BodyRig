from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_post_p0_continuation import (
    PhotorealPostP0ContinuationError,
    advance_post_p0_teacher,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Advance one verified Photoreal V2 P0 run through appearance-epoch human review "
            "to a strict static-teacher input without crossing photoreal acceptance authority."
        )
    )
    parser.add_argument("--p0-root", type=Path, required=True)
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--performer-id", default="42")
    parser.add_argument("--selected-epoch-id")
    parser.add_argument("--source-group", action="append", dest="source_groups")
    parser.add_argument("--reviewed-by")
    parser.add_argument("--review-notes")
    parser.add_argument("--approve-human-review", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = advance_post_p0_teacher(
            p0_root=args.p0_root,
            readiness_path=args.readiness,
            work_root=args.work_root,
            expected_performer_id=args.performer_id,
            selected_epoch_id=args.selected_epoch_id,
            selected_source_group_ids=args.source_groups,
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            approve_human_review=args.approve_human_review,
        )
    except PhotorealPostP0ContinuationError as exc:
        print(f"BodyRig Photoreal post-P0 continuation: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 2 if result["state"] == "human-appearance-epoch-review-required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
