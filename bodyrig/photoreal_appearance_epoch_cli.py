from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_appearance_epoch import PhotorealAppearanceEpochError
from .photoreal_appearance_epoch_readback_authority import (
    build_appearance_epoch_plan_file_strict,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a human-review-gated appearance epoch plan from a sealed BodyRig Photoreal V2 frame index."
    )
    parser.add_argument("--frame-index", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_appearance_epoch_plan_file_strict(args.frame_index, args.out)
    except PhotorealAppearanceEpochError as exc:
        print(f"BodyRig photoreal appearance epoch: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "source_frame_index_sha256": result["source_frame_index_sha256"],
                "appearance_epoch_plan_sha256": result["appearance_epoch_plan_sha256"],
                "eligible_observation_count": result["eligible_observation_count"],
                "source_group_count": result["source_group_count"],
                "human_epoch_review_required": result["human_epoch_review_required"],
                "human_epoch_review_complete": result["human_epoch_review_complete"],
                "teacher_input_authorized": result["teacher_input_authorized"],
                "teacher_training_authorized": result["teacher_training_authorized"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
