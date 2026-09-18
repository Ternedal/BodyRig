from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_teacher_authority import build_teacher_input_files_strict
from .photoreal_teacher_input import PhotorealTeacherInputError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a leakage-safe, human-epoch-approved Photoreal V2 teacher input manifest."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--frame-index", type=Path, required=True)
    parser.add_argument("--epoch-selection", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_teacher_input_files_strict(
            args.plan,
            args.receipt,
            args.frame_index,
            args.epoch_selection,
            args.out,
        )
    except PhotorealTeacherInputError as exc:
        print(f"BodyRig photoreal teacher input: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "selected_epoch_id": result["selected_epoch_id"],
                "training_source_count": result["training_source_count"],
                "held_out_evaluation_source_count": result["held_out_evaluation_source_count"],
                "training_observation_count": result["training_observation_count"],
                "held_out_evaluation_observation_count": result["held_out_evaluation_observation_count"],
                "evaluation_bytes_excluded_from_teacher_request": result["evaluation_bytes_excluded_from_teacher_request"],
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
