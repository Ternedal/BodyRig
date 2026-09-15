from __future__ import annotations

import argparse
import json
import sys

from .photoreal_animation_plan import PhotorealAnimationPlanError, build_animation_plan_files


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a Photoreal V2 P2 animation work plan from an exact human-accepted static teacher."
    )
    parser.add_argument("--static-review", required=True)
    parser.add_argument("--review-render-set", required=True)
    parser.add_argument("--teacher-manifest", required=True)
    parser.add_argument("--teacher-output-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_animation_plan_files(
            args.static_review,
            args.review_render_set,
            args.teacher_manifest,
            args.teacher_output_root,
            args.output,
        )
    except PhotorealAnimationPlanError as exc:
        print(f"BodyRig Photoreal animation plan: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "static_teacher_photoreal_accepted": result["static_teacher_photoreal_accepted"],
                "p2_animation_execution_authorized": result["p2_animation_execution_authorized"],
                "animated_teacher_acceptance_authority": result["animated_teacher_acceptance_authority"],
                "p3_device_distillation_authorized": result["p3_device_distillation_authorized"],
                "production_activation": result["production_activation"],
                "animation_plan_sha256": result["animation_plan_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
