from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_teacher_benchmark_authority import (
    build_teacher_benchmark_plan_files_strict,
    validate_teacher_benchmark_plan_files_strict,
)
from .photoreal_teacher_benchmark_plan import PhotorealTeacherBenchmarkPlanError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build the core-owned BodyRig Photoreal teacher benchmark source plan."
    )
    parser.add_argument("--teacher-input", type=Path, required=True)
    parser.add_argument("--scan-plan", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--reuse-existing", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output = args.out.expanduser().resolve()
        if args.reuse_existing and output.is_file():
            try:
                result = validate_teacher_benchmark_plan_files_strict(
                    args.teacher_input,
                    output,
                    scan_plan_path=args.scan_plan,
                )
            except PhotorealTeacherBenchmarkPlanError:
                # One-time migration path for an earlier fail-closed benchmark plan
                # that had no executable candidate before scan-plan replay support.
                try:
                    stale = json.loads(output.read_text(encoding="utf-8-sig"))
                except (OSError, UnicodeError, json.JSONDecodeError):
                    raise
                rebuildable = (
                    isinstance(stale, dict)
                    and stale.get("format") == "bodyrig-photoreal-teacher-benchmark-plan"
                    and stale.get("version") == 1
                    and stale.get("benchmark") == "exavatar"
                    and stale.get("benchmark_execution_authorized") is False
                    and stale.get("selected_source_key") is None
                    and stale.get("production_activation") is False
                    and args.scan_plan is not None
                )
                if not rebuildable:
                    raise
                output.unlink()
                result = build_teacher_benchmark_plan_files_strict(
                    args.teacher_input,
                    output,
                    scan_plan_path=args.scan_plan,
                )
        else:
            result = build_teacher_benchmark_plan_files_strict(
                args.teacher_input,
                output,
                scan_plan_path=args.scan_plan,
            )
    except (OSError, PhotorealTeacherBenchmarkPlanError) as exc:
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
