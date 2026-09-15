from __future__ import annotations

import argparse
import json
import os
import sys

from .photoreal_source_verify import PhotorealSourceVerifyError, verify_inventory_file


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify every Photoreal V2 Stash source against readable local bytes and SHA-256."
    )
    parser.add_argument("inventory")
    parser.add_argument("--path-map", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--stash-url", default=os.environ.get("STASH_URL", ""))
    args = parser.parse_args(argv)
    if not str(args.stash_url or "").strip():
        print("BodyRig photoreal source verify: FAIL: --stash-url or STASH_URL is required", file=sys.stderr)
        return 1
    try:
        result = verify_inventory_file(
            args.inventory,
            args.path_map,
            args.out,
            stash_url=args.stash_url,
        )
    except (PhotorealSourceVerifyError, OSError) as exc:
        print(f"BodyRig photoreal source verify: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "PASS",
                "format": result["format"],
                "performer_id": result["performer_id"],
                "source_count": result["source_count"],
                "video_count": result["video_count"],
                "image_count": result["image_count"],
                "total_bytes": result["total_bytes"],
                "production_activation": result["production_activation"],
            },
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
