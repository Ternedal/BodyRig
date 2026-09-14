from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_scan_plan import PhotorealScanPlanError, build_scan_plan_files


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic byte-bound scout scan plan for Photoreal V2."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_scan_plan_files(args.plan, args.receipt, args.out)
    except PhotorealScanPlanError as exc:
        print(f"BodyRig photoreal scan plan: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "source_count": result["source_count"],
                "planned_observation_count": result["planned_observation_count"],
                "strategy": result["strategy"],
                "frame_analyzer_required": result["frame_analyzer_required"],
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
