from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_identity_calibration import PhotorealIdentityCalibrationError
from .photoreal_identity_calibration_authority import build_identity_calibration_authorized_files


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Derive a source-calibrated identity match threshold for BodyRig Photoreal V2."
    )
    parser.add_argument("--identity-bank", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--negative-observations", type=Path, required=True)
    parser.add_argument(
        "--negative-inventory",
        type=Path,
        default=None,
        help="Negative inventory to revalidate. Defaults to identity-negative-inventory.json beside --plan.",
    )
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    negative_inventory = args.negative_inventory
    if negative_inventory is None:
        negative_inventory = args.plan.parent / "identity-negative-inventory.json"
    try:
        result = build_identity_calibration_authorized_files(
            args.identity_bank,
            args.plan,
            args.negative_observations,
            negative_inventory,
            args.out,
        )
    except PhotorealIdentityCalibrationError as exc:
        print(f"BodyRig photoreal identity calibration: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "target_performer_id": result["target_performer_id"],
                "positive_reference_count": result["positive_reference_count"],
                "negative_observation_count": result["negative_observation_count"],
                "negative_performer_count": result["negative_performer_count"],
                "observed_separation_margin": result["observed_separation_margin"],
                "match_threshold": result["match_threshold"],
                "match_threshold_calibrated": result["match_threshold_calibrated"],
                "identity_matching_authorized": result["identity_matching_authorized"],
                "calibration_blockers": result["calibration_blockers"],
                "identity_calibration_sha256": result["identity_calibration_sha256"],
                "teacher_training_authorized": result["teacher_training_authorized"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result["identity_matching_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
