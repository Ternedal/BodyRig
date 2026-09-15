from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_exavatar_preflight import PhotorealExAvatarPreflightError
from .photoreal_exavatar_preflight_strict import build_exavatar_preflight_strict_files


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit pinned ExAvatar benchmark code, local model assets and executable dependencies.")
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--reference-model-root", type=Path, required=True)
    parser.add_argument("--smplx-gender", choices=("female", "male", "neutral"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-colmap", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_exavatar_preflight_strict_files(
            dependency_root=args.dependency_root,
            asset_root=args.asset_root,
            reference_model_root=args.reference_model_root,
            smplx_gender=args.smplx_gender,
            output_path=args.out,
            require_colmap=not args.no_colmap,
        )
    except PhotorealExAvatarPreflightError as exc:
        print(f"BodyRig Photoreal ExAvatar preflight: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "smplx_gender": result["smplx_gender"],
                "benchmark_environment_ready": result["benchmark_environment_ready"],
                "blocker_count": len(result["blockers"]),
                "blockers": result["blockers"],
                "strict_upstream_asset_inventory": result["strict_upstream_asset_inventory"],
                "automatic_restricted_asset_download": result["automatic_restricted_asset_download"],
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result["benchmark_environment_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
