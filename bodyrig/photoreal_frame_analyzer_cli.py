from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_frame_analyzer_runner import (
    PhotorealFrameAnalyzerError,
    run_external_frame_analyzer_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run one strict external Photoreal V2 frame analyzer over a byte-bound scout plan."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--scan-plan", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.out.expanduser().resolve()
    if output.exists():
        print(f"BodyRig photoreal frame analyzer: FAIL: output already exists: {output}", file=sys.stderr)
        return 1
    try:
        result = run_external_frame_analyzer_files(
            args.config,
            args.scan_plan,
            args.workspace,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (OSError, PhotorealFrameAnalyzerError) as exc:
        print(f"BodyRig photoreal frame analyzer: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "analyzer": result["analyzer"],
                "analyzer_revision": result["analyzer_revision"],
                "observation_count": len(result["observations"]),
                "build_only": result["build_only"],
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
