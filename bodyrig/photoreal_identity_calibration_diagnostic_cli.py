from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_identity_calibration_diagnostic import (
    PhotorealIdentityCalibrationDiagnosticError,
    build_identity_calibration_diagnostic_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Explain BodyRig Photoreal Stage-13 identity calibration "
            "separation without granting authority."
        )
    )
    parser.add_argument("--identity-bank", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument(
        "--negative-observations",
        type=Path,
        required=True,
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--top-matches", type=int, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_identity_calibration_diagnostic_files(
            args.identity_bank,
            args.plan,
            args.negative_observations,
            args.out,
            top_matches=args.top_matches,
        )
    except PhotorealIdentityCalibrationDiagnosticError as exc:
        print(
            "BodyRig photoreal identity calibration diagnostic: "
            f"FAIL: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "target_performer_id":
                    result["target_performer_id"],
                "positive_floor":
                    result["positive_floor"],
                "negative_ceiling":
                    result["negative_ceiling"],
                "observed_separation_margin":
                    result["observed_separation_margin"],
                "violating_negative_observation_count":
                    result[
                        "violating_negative_observation_count"
                    ],
                "highest_negative_match":
                    result["highest_negative_match"],
                "diagnostic_only":
                    result["diagnostic_only"],
                "identity_matching_authority":
                    result["identity_matching_authority"],
                "production_activation":
                    result["production_activation"],
                "output":
                    str(args.out.expanduser().resolve()),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
