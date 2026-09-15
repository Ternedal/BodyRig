from __future__ import annotations

import argparse
import json
import sys

from .photoreal_animated_review_authority import (
    PhotorealAnimatedReviewAuthorityError,
    build_animated_review_plan_files_strict,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a human-selected Photoreal V2 P2 animated-teacher review evidence plan."
    )
    parser.add_argument("--animation-execution-receipt", required=True)
    parser.add_argument("--held-out-reference-catalog", required=True)
    parser.add_argument("--selection-input", required=True)
    parser.add_argument("--animation-output-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_animated_review_plan_files_strict(
            args.animation_execution_receipt,
            args.held_out_reference_catalog,
            args.selection_input,
            args.animation_output_root,
            args.output,
        )
    except PhotorealAnimatedReviewAuthorityError as exc:
        print(f"BodyRig Photoreal animated review plan: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "selection_count": result["selection_count"],
                "held_out_evaluation_only": result["held_out_evaluation_only"],
                "animation_artifact_bytes_reverified": result["animation_artifact_bytes_reverified"],
                "reference_motion_bytes_materialized": result["reference_motion_bytes_materialized"],
                "animated_teacher_acceptance_authority": result["animated_teacher_acceptance_authority"],
                "p3_device_distillation_authorized": result["p3_device_distillation_authorized"],
                "production_activation": result["production_activation"],
                "animated_review_plan_sha256": result["animated_review_plan_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
