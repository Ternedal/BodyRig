from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_appearance_epoch_handoff import (
    PhotorealAppearanceEpochHandoffError,
    build_appearance_epoch_review_handoff_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a non-authoritative human review handoff and editable review template "
            "for a BodyRig Photoreal V2 appearance epoch plan."
        )
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--handoff-out", type=Path, required=True)
    parser.add_argument("--review-template-out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        handoff, review_template = build_appearance_epoch_review_handoff_files(
            args.plan,
            args.handoff_out,
            args.review_template_out,
        )
    except PhotorealAppearanceEpochHandoffError as exc:
        print(f"BodyRig photoreal appearance epoch handoff: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": handoff["format"],
                "version": handoff["version"],
                "performer_id": handoff["performer_id"],
                "source_group_count": handoff["source_group_count"],
                "train_source_group_count": handoff["train_source_group_count"],
                "evaluation_source_group_count": handoff["evaluation_source_group_count"],
                "human_review_complete": handoff["human_review_complete"],
                "human_approved": handoff["human_approved"],
                "teacher_input_authorized": handoff["teacher_input_authorized"],
                "teacher_training_authorized": handoff["teacher_training_authorized"],
                "production_activation": handoff["production_activation"],
                "review_template_ready_for_human_edit": review_template["human_review_complete"] is False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
