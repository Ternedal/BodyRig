from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_teacher_review_materializer import (
    PhotorealTeacherReviewMaterializerError,
    build_materializer_config,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the pinned WSL config for exact Photoreal held-out frame materialization.")
    parser.add_argument("--windows-python", type=Path, required=True)
    parser.add_argument("--bridge-path", type=Path, required=True)
    parser.add_argument("--adapter-path", type=Path, required=True)
    parser.add_argument("--distribution", default="Ubuntu-22.04")
    parser.add_argument("--linux-python", default="/opt/bodyrig-photoreal/bin/python")
    parser.add_argument("--wsl-exe", default="wsl.exe")
    parser.add_argument("--timeout-seconds", type=int, default=86400)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_materializer_config(
            windows_python=args.windows_python,
            bridge_path=args.bridge_path,
            adapter_path=args.adapter_path,
            distribution=args.distribution,
            linux_python=args.linux_python,
            wsl_exe=args.wsl_exe,
            timeout_seconds=args.timeout_seconds,
        )
        output = args.out.expanduser().resolve()
        if output.exists():
            raise PhotorealTeacherReviewMaterializerError(f"materializer config already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    except PhotorealTeacherReviewMaterializerError as exc:
        print(f"BodyRig reference materializer config: FAIL: {exc}", file=sys.stderr)
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
