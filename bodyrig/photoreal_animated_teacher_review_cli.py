from __future__ import annotations

import argparse
import json
import sys

from .photoreal_animated_teacher_review import (
    PhotorealAnimatedTeacherReviewError,
    finalize_animated_teacher_review_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record a create-only human PASS or FAIL for the exact Photoreal V2 animated teacher."
    )
    parser.add_argument("--animation-execution-receipt", required=True)
    parser.add_argument("--animated-review-plan", required=True)
    parser.add_argument("--motion-materialization-receipt", required=True)
    parser.add_argument("--human-review-input", required=True)
    parser.add_argument("--animation-output-root", required=True)
    parser.add_argument("--motion-output-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = finalize_animated_teacher_review_files(
            args.animation_execution_receipt,
            args.animated_review_plan,
            args.motion_materialization_receipt,
            args.human_review_input,
            args.animation_output_root,
            args.motion_output_root,
            args.output,
        )
    except PhotorealAnimatedTeacherReviewError as exc:
        print(f"BodyRig Photoreal animated teacher human review: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "human_animated_review_outcome": result["human_animated_review_outcome"],
                "human_animated_review_pass": result["human_animated_review_pass"],
                "animated_teacher_acceptance_authority": result["animated_teacher_acceptance_authority"],
                "p3_device_distillation_authorized": result["p3_device_distillation_authorized"],
                "production_activation": result["production_activation"],
                "animated_teacher_review_sha256": result["animated_teacher_review_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
