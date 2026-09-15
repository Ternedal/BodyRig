from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_exavatar_materializer import (
    PhotorealExAvatarMaterializerError,
    materialize_exavatar_benchmark_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize exact BodyRig-authorized ExAvatar benchmark frames through WSL.")
    parser.add_argument("--benchmark-plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--tool-path", type=Path, required=True)
    parser.add_argument("--distribution", default="Ubuntu-22.04")
    parser.add_argument("--linux-python", default="/opt/bodyrig-photoreal/bin/python")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = materialize_exavatar_benchmark_files(
            args.benchmark_plan,
            workspace=args.workspace,
            tool_path=args.tool_path,
            distribution=args.distribution,
            linux_python=args.linux_python,
            wsl_exe=args.wsl_exe,
        )
    except PhotorealExAvatarMaterializerError as exc:
        print(f"BodyRig Photoreal ExAvatar materializer: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "source_key": result["source_key"],
                "frame_count": result["frame_count"],
                "exact_p0_frame_hashes_reproduced": result["exact_p0_frame_hashes_reproduced"],
                "held_out_evaluation_disclosed": result["held_out_evaluation_disclosed"],
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                "production_activation": result["production_activation"],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
