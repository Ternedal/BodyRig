from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Mapping

from .photoreal_source_verify import PhotorealSourceVerifyError, verify_inventory_file


def _human_bytes(value: Any) -> str:
    try:
        size = max(0, int(value))
    except (TypeError, ValueError):
        size = 0
    units = ("B", "KiB", "MiB", "GiB", "TiB")
    amount = float(size)
    for unit in units[:-1]:
        if amount < 1024.0:
            return f"{amount:.1f} {unit}"
        amount /= 1024.0
    return f"{amount:.1f} {units[-1]}"


def _progress(event: Mapping[str, Any]) -> None:
    phase = str(event.get("phase") or "")
    source_index = int(event.get("source_index") or 0)
    source_count = int(event.get("source_count") or 0)
    kind = str(event.get("kind") or "source")
    size_bytes = int(event.get("size_bytes") or 0)
    prefix = f"BodyRig source verify: [{source_index}/{source_count}] {kind}"

    if phase == "source-start":
        print(f"{prefix} hashing {_human_bytes(size_bytes)}", file=sys.stderr, flush=True)
    elif phase == "hash-progress":
        processed = int(event.get("source_bytes_hashed") or 0)
        percent = 100.0 if size_bytes <= 0 else min(100.0, processed * 100.0 / size_bytes)
        print(
            f"{prefix} {_human_bytes(processed)}/{_human_bytes(size_bytes)} ({percent:.1f}%)",
            file=sys.stderr,
            flush=True,
        )
    elif phase == "source-complete":
        verified = int(event.get("verified_bytes_total") or 0)
        print(
            f"{prefix} verified | cumulative={_human_bytes(verified)}",
            file=sys.stderr,
            flush=True,
        )


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
            progress=_progress,
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
