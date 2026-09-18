from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_appearance_epoch_review_recorder import (
    PhotorealAppearanceEpochReviewRecorderError,
    build_human_review_record_file,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Record an explicit human appearance-epoch approval from a validated BodyRig Photoreal V2 review handoff."
        )
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--selected-epoch-id", required=True)
    parser.add_argument(
        "--source-group",
        action="append",
        required=True,
        dest="source_groups",
        help="Selected source group id. Repeat for every selected train/evaluation group.",
    )
    parser.add_argument("--reviewed-by", required=True)
    parser.add_argument("--review-notes", required=True)
    parser.add_argument(
        "--approve-human-review",
        action="store_true",
        help="Explicitly confirm that a human completed the appearance-epoch review and approves the selected epoch/groups.",
    )
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        review = build_human_review_record_file(
            args.plan,
            args.handoff,
            args.out,
            selected_epoch_id=args.selected_epoch_id,
            selected_source_group_ids=args.source_groups,
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            approve_human_review=args.approve_human_review,
        )
    except PhotorealAppearanceEpochReviewRecorderError as exc:
        print(f"BodyRig photoreal appearance epoch review record: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": review["format"],
                "version": review["version"],
                "performer_id": review["performer_id"],
                "selected_epoch_id": review["selected_epoch_id"],
                "selected_source_group_count": len(review["selected_source_group_ids"]),
                "human_review_complete": review["human_review_complete"],
                "human_approved": review["human_approved"],
                "production_activation": review["production_activation"],
                "next_command": (
                    "bodyrig-photoreal-appearance-epoch-review --plan <PLAN> "
                    "--human-review <THIS_REVIEW> --out <SELECTION>"
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
