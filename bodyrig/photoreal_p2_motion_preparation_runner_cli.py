from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_p2_motion_preparation_runner import (
    PhotorealP2MotionPreparationRunnerError,
    run_motion_preparation_files,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run fail-closed P2 motion preparation and emit a core-verified execution receipt."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--handoff", type=Path, required=True)
    parser.add_argument("--private-index", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--input-plan", type=Path, required=True)
    parser.add_argument("--normalization-selection", type=Path, required=True)
    parser.add_argument("--window-selection", type=Path, required=True)
    parser.add_argument("--scan-plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        receipt = run_motion_preparation_files(
            args.config,
            args.handoff,
            args.private_index,
            args.selection,
            args.input_plan,
            args.normalization_selection,
            args.window_selection,
            args.scan_plan,
            args.workspace,
        )
    except PhotorealP2MotionPreparationRunnerError as exc:
        print(f"BodyRig P2 motion preparation: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "P2_MOTION_PREPARATION_COMPLETE",
                "task_count": receipt["task_count"],
                "source_media_rehash_performed": False,
                "motion_input_preparation_complete": True,
                "p2_animation_execution_authorized": True,
                "p2_animated_teacher_acceptance_authority": False,
                "quest_distillation_authorized": False,
                "photoreal_acceptance_authority": False,
                "production_activation": False,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
