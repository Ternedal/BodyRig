from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_teacher_benchmark_plan import (
    PhotorealTeacherBenchmarkPlanError,
    build_teacher_benchmark_plan_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the core-owned BodyRig Photoreal teacher benchmark source plan."
    )
    parser.add_argument("--teacher-input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_teacher_benchmark_plan_files(args.teacher_input, args.out)
    except PhotorealTeacherBenchmarkPlanError as exc:
        print(f"BodyRig Photoreal teacher benchmark plan: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "benchmark": result["benchmark"],
                "candidate_count": result["candidate_count"],
                "selected_source_key": result["selected_source_key"],
                "selected_observation_count": result["selected_observation_count"],
                "intended_source_utilization_fraction": result["intended_source_utilization_fraction"],
                "intended_observation_utilization_fraction": result["intended_observation_utilization_fraction"],
                "benchmark_execution_authorized": result["benchmark_execution_authorized"],
                "benchmark_blockers": result["benchmark_blockers"],
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result["benchmark_execution_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
