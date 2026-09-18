from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .photoreal_inventory_path_map import (
    PhotorealInventoryPathMapError,
    build_inventory_path_map_file,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an exact Photoreal V2 Stash path-map proof from authoritative source inventories."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument(
        "--negative-inventory",
        type=Path,
        default=None,
        help="Optional authoritative identity-negative inventory to include in the exact path-map proof.",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stash-url", default=os.environ.get("STASH_URL", ""))
    args = parser.parse_args(argv)

    if not str(args.stash_url or "").strip():
        print("BodyRig photoreal inventory path map: FAIL: --stash-url or STASH_URL is required", file=sys.stderr)
        return 1
    try:
        result = build_inventory_path_map_file(
            args.inventory,
            args.out,
            stash_url=args.stash_url,
            negative_inventory_path=args.negative_inventory,
        )
    except (PhotorealInventoryPathMapError, OSError) as exc:
        print(f"BodyRig photoreal inventory path map: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "PASS",
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_ids"][0],
                "mapping_count": len(result["mapping"]),
                "proof_count": len(result["proof"]),
                "includes_negative_inventory": args.negative_inventory is not None,
                "production_activation": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
