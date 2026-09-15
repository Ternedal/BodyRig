from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_gaussianavatar_materializer import (
    PhotorealGaussianAvatarMaterializerError,
    materialize_gaussianavatar_benchmark,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize exact BodyRig-authorized train frames for GaussianAvatar.")
    parser.add_argument("--comparison-plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--tool", type=Path, required=True)
    parser.add_argument("--distribution", default="Ubuntu-22.04")
    parser.add_argument("--linux-python", default="/opt/bodyrig-photoreal/bin/python")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        try:
            plan = json.loads(args.comparison_plan.expanduser().resolve().read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PhotorealGaussianAvatarMaterializerError("teacher comparison plan is unreadable") from exc
        if not isinstance(plan, dict):
            raise PhotorealGaussianAvatarMaterializerError("teacher comparison plan must be a JSON object")
        receipt = materialize_gaussianavatar_benchmark(
            plan,
            workspace=args.workspace,
            tool_path=args.tool,
            distribution=args.distribution,
            linux_python=args.linux_python,
            wsl_exe=args.wsl_exe,
        )
    except PhotorealGaussianAvatarMaterializerError as exc:
        print(f"BodyRig Photoreal GaussianAvatar materialization: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "format": receipt["format"],
        "version": receipt["version"],
        "benchmark": receipt["benchmark"],
        "frame_count": receipt["frame_count"],
        "smpl_gender": receipt["smpl_gender"],
        "smpl_type": receipt["smpl_type"],
        "exact_p0_frame_hashes_reproduced": receipt["exact_p0_frame_hashes_reproduced"],
        "held_out_evaluation_disclosed": receipt["held_out_evaluation_disclosed"],
        "photoreal_acceptance_authority": receipt["photoreal_acceptance_authority"],
        "production_activation": receipt["production_activation"],
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
