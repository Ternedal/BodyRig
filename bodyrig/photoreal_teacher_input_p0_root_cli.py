from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_teacher_input_p0_root import (
    PhotorealTeacherInputP0RootError,
    build_teacher_input_from_p0_root,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build strict Photoreal V2 teacher input from one authorized P0 output root plus an approved appearance epoch selection."
    )
    parser.add_argument("--p0-root", type=Path, required=True)
    parser.add_argument("--epoch-selection", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_teacher_input_from_p0_root(args.p0_root, args.epoch_selection, args.out)
    except PhotorealTeacherInputP0RootError as exc:
        print(f"BodyRig photoreal teacher input from P0 root: FAIL: {exc}", file=sys.stderr)
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
