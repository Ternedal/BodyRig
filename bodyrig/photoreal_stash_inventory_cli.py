from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any, Mapping

from .photoreal_stash_inventory import (
    PhotorealStashInventoryError,
    fetch_photoreal_source_inventory,
    write_inventory,
)
from .stash_source import StashClient, StashConfig, StashSourceError


def _tag_hints(tags: Any) -> set[str]:
    if not isinstance(tags, list):
        return set()
    normalized = " ".join(
        str(tag).lower().replace("_", " ").replace("-", " ")
        for tag in tags
        if isinstance(tag, str)
    )
    compact = "".join(normalized.split())
    words = set(normalized.split())
    hints: set[str] = set()
    if "equirectangular" in compact or "panorama" in compact or "panoramic" in compact:
        hints.add("equirectangular")
    if "fisheye" in compact or ("fish" in words and "eye" in words):
        hints.add("fisheye")
    if "mesh" in words or "spherical" in words or "sphericalvideo" in compact:
        hints.add("mesh-or-spherical")
    return hints


def _projection_diagnostics(inventory: Mapping[str, Any]) -> dict[str, Any]:
    raw_videos = inventory.get("videos")
    videos = [item for item in raw_videos if isinstance(item, Mapping)] if isinstance(raw_videos, list) else []
    projection_counts = Counter(str(item.get("projection") or "unknown") for item in videos)
    stereo_counts = Counter(str(item.get("stereo_layout") or "unknown") for item in videos)
    spatial = [
        item
        for item in videos
        if str(item.get("projection") or "unknown") != "flat"
        or str(item.get("stereo_layout") or "unknown") != "mono"
    ]
    hint_counts: Counter[str] = Counter()
    for item in spatial:
        for hint in _tag_hints(item.get("tags")):
            hint_counts[hint] += 1
    return {
        "diagnostic_only": True,
        "authority": False,
        "spatial_source_count": len(spatial),
        "projection_counts": dict(sorted(projection_counts.items())),
        "stereo_layout_counts": dict(sorted(stereo_counts.items())),
        "spatial_projection_tag_hint_counts": dict(sorted(hint_counts.items())),
        "container_projection_metadata_probe_required": bool(spatial),
        "production_activation": False,
    }


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
    print(
        "BodyRig Photoreal V2 projection diagnostics: "
        + json.dumps(_projection_diagnostics(inventory), separators=(",", ":"), sort_keys=True)
    )
    print(json.dumps({"output": str(output), "performer": inventory["performer"]}, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
