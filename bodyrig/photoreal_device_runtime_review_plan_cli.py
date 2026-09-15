from __future__ import annotations

import argparse
import json
import sys

from .photoreal_device_runtime_review_plan import (
    PhotorealDeviceRuntimeReviewPlanError,
    build_device_runtime_review_plan_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a Photoreal V2 physical-device runtime review plan from an exact P3 distillation execution receipt."
    )
    parser.add_argument("--distillation-plan", required=True)
    parser.add_argument("--distillation-execution-receipt", required=True)
    parser.add_argument("--student-output-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_device_runtime_review_plan_files(
            args.distillation_plan,
            args.distillation_execution_receipt,
            args.student_output_root,
            args.output,
        )
    except PhotorealDeviceRuntimeReviewPlanError as exc:
        print(f"BodyRig Photoreal device runtime review plan: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "target_model": result["target_profile"]["target_model"],
                "student_representation": result["student_representation"],
                "student_artifact_count": result["student_artifact_count"],
                "physical_device_evidence_required": result["physical_device_evidence_required"],
                "physical_device_evidence_present": result["physical_device_evidence_present"],
                "runtime_acceptance_authority": result["runtime_acceptance_authority"],
                "production_activation": result["production_activation"],
                "device_runtime_review_plan_sha256": result["device_runtime_review_plan_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
