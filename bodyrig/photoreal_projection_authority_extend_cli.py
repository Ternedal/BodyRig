from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .photoreal_projection_authority_extend import (
    PhotorealProjectionAuthorityExtensionError,
    extend_verified_vr180_manifest,
)


def _read_json(path: str | Path, *, label: str) -> dict[str, Any]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealProjectionAuthorityExtensionError(f"{label} is unreadable JSON: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealProjectionAuthorityExtensionError(f"{label} must be a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extend a SHA-bound Photoreal projection authority only for newly spatial sources."
    )
    parser.add_argument("--plan", required=True)
    parser.add_argument("--receipt", required=True)
    parser.add_argument("--prior-authority", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--new-stereo-layout", required=True, choices=("side-by-side", "over-under", "mono"))
    parser.add_argument("--operator-verified-new-vr180-equi", action="store_true")
    args = parser.parse_args(argv)

    try:
        plan = _read_json(args.plan, label="photoreal dataset plan")
        receipt = _read_json(args.receipt, label="photoreal source receipt")
        prior = _read_json(args.prior_authority, label="prior projection authority")
        manifest, missing = extend_verified_vr180_manifest(
            plan,
            receipt,
            prior,
            new_stereo_layout=args.new_stereo_layout,
            operator_verified_new_sources=args.operator_verified_new_vr180_equi,
        )
        output = Path(args.out).expanduser().resolve()
        if output.exists():
            raise PhotorealProjectionAuthorityExtensionError(
                f"projection authority extension output already exists: {output}"
            )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        print(json.dumps({
            "status": "PASS",
            "performer_id": manifest["performer_id"],
            "prior_source_count": len(prior["sources"]),
            "new_source_count": len(missing),
            "new_source_keys": missing,
            "total_source_count": len(manifest["sources"]),
            "new_stereo_layout": args.new_stereo_layout,
            "operator_verified_new_sources": True,
            "production_activation": False,
            "output": str(output),
        }, sort_keys=True))
        return 0
    except PhotorealProjectionAuthorityExtensionError as exc:
        print(f"BodyRig projection authority extension: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
