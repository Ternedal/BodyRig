from __future__ import annotations

import argparse
import json
import sys

from .photoreal_p0_crash_receipt import (
    PhotorealP0CrashReceiptError,
    build_p0_crash_receipt,
    write_p0_crash_receipt,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a fail-closed BodyRig Photoreal P0 unexpected-failure receipt."
    )
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--performer-id", required=True)
    parser.add_argument("--failed-stage-number", required=True, type=int)
    parser.add_argument("--failed-stage-label", required=True)
    parser.add_argument("--error-message", required=True)
    parser.add_argument("--output-root", required=True)
    parser.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt = build_p0_crash_receipt(
            bodyrig_revision=args.bodyrig_revision,
            performer_id=args.performer_id,
            failed_stage_number=args.failed_stage_number,
            failed_stage_label=args.failed_stage_label,
            error_message=args.error_message,
            output_root=args.output_root,
        )
        receipt = write_p0_crash_receipt(receipt, args.output)
    except PhotorealP0CrashReceiptError as exc:
        print(f"BodyRig Photoreal P0 crash receipt: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": receipt["format"],
                "version": receipt["version"],
                "failed_stage_number": receipt["failed_stage_number"],
                "failed_stage_label": receipt["failed_stage_label"],
                "artifact_present_count": receipt["artifact_present_count"],
                "teacher_training_authorized": receipt["teacher_training_authorized"],
                "photoreal_acceptance_authority": receipt["photoreal_acceptance_authority"],
                "production_activation": receipt["production_activation"],
                "p0_crash_receipt_sha256": receipt["p0_crash_receipt_sha256"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
