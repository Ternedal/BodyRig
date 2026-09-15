from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_static_teacher_review import (
    PhotorealStaticTeacherReviewError,
    finalize_static_teacher_review_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record create-only human PASS/FAIL for the exact Photoreal V2 static teacher and held-out reference bytes."
    )
    parser.add_argument("--render-set", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--materialization-receipt", type=Path, required=True)
    parser.add_argument("--human-input", type=Path, required=True)
    parser.add_argument("--teacher-output-root", type=Path, required=True)
    parser.add_argument("--reference-output-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = finalize_static_teacher_review_files(
            args.render_set,
            args.mapping,
            args.materialization_receipt,
            args.human_input,
            args.teacher_output_root,
            args.reference_output_root,
            args.out,
        )
    except PhotorealStaticTeacherReviewError as exc:
        print(f"BodyRig Photoreal static teacher review: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "format": result["format"],
        "version": result["version"],
        "performer_id": result["performer_id"],
        "selected_epoch_id": result["selected_epoch_id"],
        "human_review_complete": result["human_review_complete"],
        "human_review_outcome": result["human_review_outcome"],
        "human_review_pass": result["human_review_pass"],
        "static_teacher_photoreal_accepted": result["static_teacher_photoreal_accepted"],
        "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
        "p2_animation_work_authorized": result["p2_animation_work_authorized"],
        "production_activation": result["production_activation"],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0 if result["human_review_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
