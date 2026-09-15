from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .photoreal_identity_negative_verify import (
    PhotorealIdentityNegativeVerifyError,
    verify_identity_negative_inventory_file,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bind source-authoritative non-target identity calibration media to local bytes."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--path-map", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--stash-url", default=os.environ.get("STASH_URL", "http://localhost:9999"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = verify_identity_negative_inventory_file(
            args.inventory,
            args.path_map,
            args.out,
            stash_url=args.stash_url,
        )
    except PhotorealIdentityNegativeVerifyError as exc:
        print(f"BodyRig photoreal identity negative verify: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "target_performer_id": result["target_performer_id"],
                "negative_inventory_sha256": result["negative_inventory_sha256"],
                "negative_performer_count": result["negative_performer_count"],
                "source_count": result["source_count"],
                "total_bytes": result["total_bytes"],
                "all_sources_sha256_bound": result["all_sources_sha256_bound"],
                "identity_matching_authorized": result["identity_matching_authorized"],
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
