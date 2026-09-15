from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_device_distillation_execution_receipt import (
    PhotorealDeviceDistillationExecutionReceiptError,
    write_device_distillation_execution_receipt,
)
from .photoreal_device_distillation_runner import (
    PhotorealDeviceDistillationRunnerError,
    run_external_distillation_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a representation-neutral Photoreal V2 P3 device-distillation adapter behind the BodyRig authority boundary."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--distillation-plan", required=True)
    parser.add_argument("--animation-output-root", required=True)
    parser.add_argument("--workspace", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_external_distillation_files(
            args.config,
            args.distillation_plan,
            args.animation_output_root,
            args.workspace,
        )
        receipt_path = Path(args.workspace).expanduser().resolve() / "device-distillation-execution-receipt.json"
        receipt = write_device_distillation_execution_receipt(result, receipt_path)
    except (PhotorealDeviceDistillationRunnerError, PhotorealDeviceDistillationExecutionReceiptError) as exc:
        print(f"BodyRig Photoreal device distillation runner: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": receipt["format"],
                "version": receipt["version"],
                "performer_id": receipt["performer_id"],
                "student_representation": receipt["student_representation"],
                "distillation_complete": receipt["distillation_complete"],
                "fidelity_delta_measurement_count": len(receipt["fidelity_delta_measurements"]),
                "student_artifact_count": len(receipt["student_artifacts"]),
                "runtime_acceptance_authority": receipt["runtime_acceptance_authority"],
                "production_activation": receipt["production_activation"],
                "device_distillation_execution_receipt_sha256": receipt["device_distillation_execution_receipt_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
