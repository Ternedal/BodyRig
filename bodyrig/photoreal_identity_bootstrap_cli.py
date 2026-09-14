from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_identity_bootstrap import (
    PhotorealIdentityBootstrapError,
    build_identity_bootstrap_plan_file,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a train-only, source-authoritative identity bootstrap plan for BodyRig Photoreal V2."
    )
    parser.add_argument("--scan-plan", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_identity_bootstrap_plan_file(args.scan_plan, args.out)
    except PhotorealIdentityBootstrapError as exc:
        print(f"BodyRig photoreal identity bootstrap: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "source_count": result["source_count"],
                "source_group_count": result["source_group_count"],
                "reference_sample_count": result["reference_sample_count"],
                "train_only": result["train_only"],
                "identity_bank_build_authorized": result["identity_bank_build_authorized"],
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
