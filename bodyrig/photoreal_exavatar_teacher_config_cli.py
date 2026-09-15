from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_exavatar_teacher_config import (
    MAX_TIMEOUT_SECONDS,
    PhotorealExAvatarTeacherConfigError,
    build_exavatar_teacher_config_file,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a hash-bound BodyRig ExAvatar teacher config for WSL execution.")
    parser.add_argument("--windows-python", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, required=True)
    parser.add_argument("--adapter", type=Path, required=True)
    parser.add_argument("--linux-workspace-root", required=True)
    parser.add_argument("--linux-runtime-preflight", required=True)
    parser.add_argument("--linux-python", default="/opt/bodyrig-exavatar/bin/python")
    parser.add_argument("--distribution", default="Ubuntu-22.04")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--timeout-seconds", type=int, default=MAX_TIMEOUT_SECONDS)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_exavatar_teacher_config_file(
            output_path=args.out,
            windows_python=args.windows_python,
            bridge_path=args.bridge,
            adapter_path=args.adapter,
            linux_workspace_root=args.linux_workspace_root,
            linux_runtime_preflight=args.linux_runtime_preflight,
            linux_python=args.linux_python,
            distribution=args.distribution,
            wsl_exe=args.wsl_exe,
            timeout_seconds=args.timeout_seconds,
        )
    except PhotorealExAvatarTeacherConfigError as exc:
        print(f"BodyRig Photoreal ExAvatar teacher config: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "adapter": result["adapter"],
                "revision": result["revision"],
                "upstream_commit": result["upstream_commit"],
                "timeout_seconds": result["timeout_seconds"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
