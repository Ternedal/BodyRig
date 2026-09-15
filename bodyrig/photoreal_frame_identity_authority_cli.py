from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_frame_identity_authority import (
    PhotorealFrameIdentityAuthorityError,
    authorize_frame_identity_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply core identity authority to measurement-only photoreal frame observations."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--measurements", type=Path, required=True)
    parser.add_argument("--identity-bank", type=Path, required=True)
    parser.add_argument("--identity-calibration", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = authorize_frame_identity_files(
            args.plan,
            args.measurements,
            args.identity_bank,
            args.identity_calibration,
            args.out,
        )
    except PhotorealFrameIdentityAuthorityError as exc:
        print(f"BodyRig photoreal frame identity authority: FAIL: {exc}", file=sys.stderr)
        return 1

    verified = sum(1 for item in result["observations"] if item["target_identity_verified"])
    unresolved = len(result["observations"]) - verified
    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "identity_matching_calibrated": result["identity_matching_calibrated"],
                "identity_match_threshold": result["identity_match_threshold"],
                "observation_count": len(result["observations"]),
                "target_identity_verified_count": verified,
                "identity_unresolved_count": unresolved,
                "identity_authority_is_core_derived": result["identity_authority_is_core_derived"],
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
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
