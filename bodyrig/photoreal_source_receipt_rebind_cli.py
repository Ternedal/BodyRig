from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .photoreal_source_receipt_rebind import (
    PhotorealSourceReceiptRebindError,
    rebind_verified_source_receipt_files,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rebind a previously byte-verified Photoreal source receipt to a metadata-only "
            "inventory revision without rehashing source contents."
        )
    )
    parser.add_argument("--prior-inventory", type=Path, required=True)
    parser.add_argument("--prior-receipt", type=Path, required=True)
    parser.add_argument("--new-inventory", type=Path, required=True)
    parser.add_argument("--new-path-map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--proof-out", type=Path, required=True)
    parser.add_argument("--stash-url", default=os.environ.get("STASH_URL", ""))
    args = parser.parse_args(argv)
    if not str(args.stash_url or "").strip():
        print("BodyRig source receipt rebind: FAIL: --stash-url or STASH_URL is required", file=sys.stderr)
        return 1

    try:
        receipt, proof = rebind_verified_source_receipt_files(
            prior_inventory_path=args.prior_inventory,
            prior_receipt_path=args.prior_receipt,
            new_inventory_path=args.new_inventory,
            new_path_map_path=args.new_path_map,
            output_path=args.out,
            proof_output_path=args.proof_out,
            stash_url=str(args.stash_url),
        )
    except (PhotorealSourceReceiptRebindError, OSError) as exc:
        print(f"BodyRig source receipt rebind: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "PASS",
                "format": receipt["format"],
                "performer_id": receipt["performer_id"],
                "source_count": receipt["source_count"],
                "total_bytes": receipt["total_bytes"],
                "source_rehash_skipped_explicitly": proof["source_rehash_skipped_explicitly"],
                "all_source_records_exactly_preserved": proof["all_source_records_exactly_preserved"],
                "all_current_sizes_match_verified_receipt": proof["all_current_sizes_match_verified_receipt"],
                "production_activation": receipt["production_activation"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
