from __future__ import annotations

import argparse
import json
import sys

from .photoreal_dataset_plan import PhotorealDatasetPlanError, build_dataset_plan_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build a leakage-safe train/evaluation source split for BodyRig Photoreal V2."
    )
    parser.add_argument("inventory")
    parser.add_argument("--out", required=True)
    parser.add_argument("--eval-fraction", type=float, default=0.20)
    parser.add_argument("--seed", default="bodyrig-photoreal-v2")
    args = parser.parse_args(argv)
    try:
        result = build_dataset_plan_file(
            args.inventory,
            args.out,
            eval_fraction=args.eval_fraction,
            seed=args.seed,
        )
    except PhotorealDatasetPlanError as exc:
        print(f"BodyRig photoreal dataset plan: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "PASS",
                "format": result["format"],
                "performer_id": result["performer_id"],
                "group_count": result["group_count"],
                "train_group_count": result["train_group_count"],
                "evaluation_group_count": result["evaluation_group_count"],
                "teacher_training_authorized": result["teacher_training_authorized"],
            },
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
