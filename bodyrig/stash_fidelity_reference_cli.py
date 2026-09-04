from __future__ import annotations

import argparse
import json
import os
import sys

from .stash_fidelity_reference import StashFidelityReferenceError, materialize_reference_set
from .stash_source import StashClient, StashConfig, StashSourceError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize a private, hash-bound Stash performer visual-fidelity reference set."
    )
    parser.add_argument("--performer-id", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--url", default="")
    parser.add_argument("--api-key-env", default="STASH_API_KEY")
    parser.add_argument("--limit", type=int, default=24)
    args = parser.parse_args(argv)

    try:
        url = (args.url or os.environ.get("STASH_URL") or "").strip()
        if not url:
            raise StashFidelityReferenceError("Stash URL is required via --url or STASH_URL")
        api_key = os.environ.get(args.api_key_env, "") if args.api_key_env else ""
        client = StashClient(StashConfig(url=url, api_key=api_key))
        result = materialize_reference_set(
            client,
            args.performer_id,
            output_dir=args.out,
            limit=args.limit,
        )
    except (StashSourceError, StashFidelityReferenceError, OSError, ValueError) as exc:
        print(f"BodyRig Stash fidelity references: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
