from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_identity_bank import PhotorealIdentityBankError, build_identity_bank_files


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a train-only, model-bound identity reference bank for BodyRig Photoreal V2."
    )
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--model-set", type=Path, required=True)
    parser.add_argument("--observations", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_identity_bank_files(
            args.bootstrap,
            args.model_set,
            args.observations,
            args.out,
        )
    except PhotorealIdentityBankError as exc:
        print(f"BodyRig photoreal identity bank: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "reference_count": result["reference_count"],
                "source_group_count": result["source_group_count"],
                "model_set_sha256": result["model_set_sha256"],
                "identity_bank_sha256": result["identity_bank_sha256"],
                "match_threshold_calibrated": result["match_threshold_calibrated"],
                "identity_matching_authorized": result["identity_matching_authorized"],
                "teacher_training_authorized": result["teacher_training_authorized"],
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
