from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_model_set import PhotorealModelSetError, write_model_set


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Hash the exact external model assets used by the Photoreal V2 frame analyzer."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = write_model_set(args.root, args.out)
    except (OSError, PhotorealModelSetError) as exc:
        print(f"BodyRig photoreal model set: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "file_count": result["file_count"],
                "total_bytes": result["total_bytes"],
                "model_set_sha256": result["model_set_sha256"],
                "production_activation": result["production_activation"],
            },
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
