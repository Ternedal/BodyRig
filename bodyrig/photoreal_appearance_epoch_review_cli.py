from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_appearance_epoch_review import (
    PhotorealAppearanceEpochReviewError,
    apply_appearance_epoch_review_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate an explicit human appearance-epoch approval for BodyRig Photoreal V2."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--human-review", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = apply_appearance_epoch_review_files(args.plan, args.human_review, args.out)
    except PhotorealAppearanceEpochReviewError as exc:
        print(f"BodyRig photoreal appearance epoch review: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "selected_epoch_id": result["selected_epoch_id"],
                "selected_train_group_count": result["selected_train_group_count"],
                "selected_evaluation_group_count": result["selected_evaluation_group_count"],
                "human_epoch_review_complete": result["human_epoch_review_complete"],
                "human_approved": result["human_approved"],
                "teacher_input_authorized": result["teacher_input_authorized"],
                "teacher_training_authorized": result["teacher_training_authorized"],
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
