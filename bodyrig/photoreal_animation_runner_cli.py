from __future__ import annotations

import argparse
import json
import sys

from .photoreal_animation_runner import PhotorealAnimationRunnerError, run_external_animation_files


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a representation-neutral Photoreal V2 P2 animation adapter behind the BodyRig authority boundary."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--animation-plan", required=True)
    parser.add_argument("--teacher-output-root", required=True)
    parser.add_argument("--workspace", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_external_animation_files(
            args.config,
            args.animation_plan,
            args.teacher_output_root,
            args.workspace,
        )
    except PhotorealAnimationRunnerError as exc:
        print(f"BodyRig Photoreal animation runner: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "animation_complete": result["animation_complete"],
                "representation": result["representation"],
                "consumed_teacher_artifact_count": len(result["consumed_teacher_artifacts"]),
                "animation_artifact_count": len(result["animation_artifacts"]),
                "animated_teacher_acceptance_authority": result["animated_teacher_acceptance_authority"],
                "p3_device_distillation_authorized": result["p3_device_distillation_authorized"],
                "production_activation": result["production_activation"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
