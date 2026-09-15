from __future__ import annotations

import argparse
import json
import sys

from .photoreal_device_distillation_plan import (
    PhotorealDeviceDistillationPlanError,
    build_device_distillation_plan_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a fail-closed Photoreal V2 P3 device-distillation plan from an exact human-passed animated teacher."
    )
    parser.add_argument("--animated-teacher-review", required=True)
    parser.add_argument("--animation-execution-receipt", required=True)
    parser.add_argument("--target-profile", required=True)
    parser.add_argument("--animation-output-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_device_distillation_plan_files(
            args.animated_teacher_review,
            args.animation_execution_receipt,
            args.target_profile,
            args.animation_output_root,
            args.output,
        )
    except PhotorealDeviceDistillationPlanError as exc:
        print(f"BodyRig Photoreal device distillation plan: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "target_model": result["target_profile"]["target_model"],
                "target_refresh_hz": result["target_profile"]["target_refresh_hz"],
                "distillation_source_artifact_count": result["distillation_source_artifact_count"],
                "p3_distillation_execution_authorized": result["p3_distillation_execution_authorized"],
                "runtime_acceptance_authority": result["runtime_acceptance_authority"],
                "production_activation": result["production_activation"],
                "device_distillation_plan_sha256": result["device_distillation_plan_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
