from __future__ import annotations

import argparse
import json
import sys

from .photoreal_motion_reference_materializer import PhotorealMotionReferenceMaterializerError
from .photoreal_motion_reference_materializer_config import build_motion_materializer_config_file


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a pinned Photoreal V2 motion-reference materializer config")
    parser.add_argument("--output", required=True)
    parser.add_argument("--windows-python", required=True)
    parser.add_argument("--bridge-path", required=True)
    parser.add_argument("--adapter-path", required=True)
    parser.add_argument("--distribution", default="Ubuntu-22.04")
    parser.add_argument("--linux-python", default="/opt/bodyrig-photoreal/bin/python")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--timeout-seconds", type=int, default=86400)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_motion_materializer_config_file(
            output_path=args.output,
            windows_python=args.windows_python,
            bridge_path=args.bridge_path,
            adapter_path=args.adapter_path,
            distribution=args.distribution,
            linux_python=args.linux_python,
            wsl_exe=args.wsl_exe,
            timeout_seconds=args.timeout_seconds,
        )
    except PhotorealMotionReferenceMaterializerError as exc:
        print(f"BodyRig Photoreal motion materializer config: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "format": result["format"],
        "version": result["version"],
        "adapter": result["adapter"],
        "revision": result["revision"],
        "timeout_seconds": result["timeout_seconds"],
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
