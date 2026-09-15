from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_animation_execution_receipt import (
    PhotorealAnimationExecutionReceiptError,
    write_animation_execution_receipt,
)
from .photoreal_animation_runner import PhotorealAnimationRunnerError, run_external_animation_files


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a representation-neutral Photoreal V2 P2 animation adapter behind the BodyRig authority boundary."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--animation-plan", required=True)
    parser.add_argument("--teacher-output-root", required=True)
    parser.add_argument("--workspace", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_external_animation_files(
            args.config,
            args.animation_plan,
            args.teacher_output_root,
            args.workspace,
        )
        receipt = write_animation_execution_receipt(
            result,
            Path(args.workspace).expanduser().resolve() / "animation-execution-receipt.json",
        )
    except (PhotorealAnimationRunnerError, PhotorealAnimationExecutionReceiptError) as exc:
        print(f"BodyRig Photoreal animation runner: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": receipt["format"],
                "version": receipt["version"],
                "performer_id": receipt["performer_id"],
                "animation_complete": receipt["animation_complete"],
                "representation": receipt["representation"],
                "consumed_teacher_artifact_count": len(receipt["consumed_teacher_artifacts"]),
                "animation_artifact_count": len(receipt["animation_artifacts"]),
                "artifact_bytes_verified_by_core": receipt["artifact_bytes_verified_by_core"],
                "animated_teacher_acceptance_authority": receipt["animated_teacher_acceptance_authority"],
                "p3_device_distillation_authorized": receipt["p3_device_distillation_authorized"],
                "production_activation": receipt["production_activation"],
                "animation_execution_receipt_sha256": receipt["animation_execution_receipt_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
