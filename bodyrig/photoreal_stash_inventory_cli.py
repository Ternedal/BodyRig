from __future__ import annotations

import argparse
import json
import os
import sys

from .photoreal_stash_inventory import (
    PhotorealStashInventoryError,
    fetch_photoreal_source_inventory,
    write_inventory,
)
from .stash_source import StashClient, StashConfig, StashSourceError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Inventory the exhaustive Stash source universe for BodyRig Photoreal V2."
    )
    parser.add_argument("--performer-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--stash-url", default=os.environ.get("STASH_URL", "http://localhost:9999"))
    parser.add_argument("--api-key-env", default="STASH_API_KEY")
    parser.add_argument("--page-size", type=int, default=250)
    parser.add_argument("--maximum-items", type=int, default=100_000)
    args = parser.parse_args(argv)

    api_key = os.environ.get(args.api_key_env, "")
    try:
        client = StashClient(StashConfig(url=args.stash_url, api_key=api_key))
        inventory = fetch_photoreal_source_inventory(
            client,
            args.performer_id,
            page_size=args.page_size,
            maximum_items=args.maximum_items,
        )
        output = write_inventory(args.out, inventory)
    except (StashSourceError, PhotorealStashInventoryError, OSError, ValueError) as exc:
        print(f"BodyRig Photoreal V2 Stash inventory: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "BodyRig Photoreal V2 Stash inventory: PASS | "
        f"scenes={inventory['scene_count']} | videos={inventory['video_file_count']} | "
        f"galleries={inventory['gallery_count']} | images={inventory['image_file_count']} | "
        f"flat_hours={inventory['summary']['flat_video_hours']} | "
        f"spatial_hours={inventory['summary']['spatial_or_projection_video_hours']}"
    )
    print(json.dumps({"output": str(output), "performer": inventory["performer"]}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
