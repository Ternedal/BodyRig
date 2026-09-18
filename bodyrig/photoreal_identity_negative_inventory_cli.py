from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .photoreal_identity_negative_inventory import (
    PhotorealIdentityNegativeInventoryError,
    fetch_identity_negative_inventory,
)
from .stash_source import StashClient, StashConfig, StashSourceError


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Discover source-authoritative non-target identity calibration media from Stash."
    )
    parser.add_argument("--target-performer-id", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stash-url", default=os.environ.get("STASH_URL", "http://localhost:9999"))
    parser.add_argument("--api-key-env", default="STASH_API_KEY")
    parser.add_argument("--max-negative-performers", type=int, default=4)
    parser.add_argument("--sources-per-performer", type=int, default=3)
    parser.add_argument("--page-size", type=int, default=250)
    parser.add_argument("--maximum-items", type=int, default=100_000)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    output = args.out.expanduser().resolve()
    if output.exists():
        print(f"BodyRig photoreal identity negatives: FAIL: output already exists: {output}", file=sys.stderr)
        return 1
    try:
        client = StashClient(StashConfig(url=args.stash_url, api_key=os.environ.get(args.api_key_env, "")))
        result = fetch_identity_negative_inventory(
            client,
            args.target_performer_id,
            max_negative_performers=args.max_negative_performers,
            sources_per_performer=args.sources_per_performer,
            page_size=args.page_size,
            maximum_items=args.maximum_items,
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    except (PhotorealIdentityNegativeInventoryError, StashSourceError, OSError, ValueError) as exc:
        print(f"BodyRig photoreal identity negatives: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "target_performer_id": result["target_performer_id"],
                "negative_performer_count": result["negative_performer_count"],
                "source_count": result["source_count"],
                "calibration_only": result["calibration_only"],
                "identity_matching_authorized": result["identity_matching_authorized"],
                "production_activation": result["production_activation"],
                "output": str(output),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
