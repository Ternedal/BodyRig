from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_identity_calibration_plan import (
    PhotorealIdentityCalibrationPlanError,
    build_identity_calibration_plan_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a byte-bound non-target identity calibration sample plan for BodyRig Photoreal V2."
    )
    parser.add_argument("--identity-bank", type=Path, required=True)
    parser.add_argument("--negative-receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_identity_calibration_plan_files(
            args.identity_bank,
            args.negative_receipt,
            args.out,
        )
    except PhotorealIdentityCalibrationPlanError as exc:
        print(f"BodyRig photoreal identity calibration plan: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "target_performer_id": result["target_performer_id"],
                "negative_performer_count": result["negative_performer_count"],
                "source_count": result["source_count"],
                "planned_negative_observation_count": result["planned_negative_observation_count"],
                "identity_bank_sha256": result["identity_bank_sha256"],
                "model_set_sha256": result["model_set_sha256"],
                "identity_matching_authorized": result["identity_matching_authorized"],
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
