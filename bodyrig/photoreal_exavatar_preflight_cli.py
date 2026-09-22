from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_exavatar_preflight import PUBLIC_TOOL_LAYOUT, PhotorealExAvatarPreflightError
from .photoreal_exavatar_preflight_strict import (
    build_exavatar_preflight_strict_files,
    validate_exavatar_preflight_strict_file,
)




def _is_migratable_unreadable_dependency_receipt(path: Path) -> bool:
    try:
        existing = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    if not isinstance(existing, dict):
        return False
    if existing.get("format") != "bodyrig-photoreal-exavatar-preflight":
        return False
    if type(existing.get("version")) is not int or existing.get("version") != 1:
        return False
    if existing.get("strict_upstream_asset_inventory") is not True:
        return False
    if existing.get("benchmark_environment_ready") is not False:
        return False
    if existing.get("photoreal_acceptance_authority") is not False:
        return False
    if existing.get("production_activation") is not False:
        return False
    blockers = existing.get("blockers")
    if not isinstance(blockers, list) or not all(isinstance(item, str) for item in blockers):
        return False
    expected = sorted(
        f"dependency is not a readable git checkout: {relative}"
        for relative in PUBLIC_TOOL_LAYOUT.values()
    )
    return sorted(blockers) == expected

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit pinned ExAvatar benchmark code, local model assets and executable dependencies.")
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--reference-model-root", type=Path, required=True)
    parser.add_argument("--smplx-gender", choices=("female", "male", "neutral"), required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--no-colmap", action="store_true")
    parser.add_argument(
        "--reuse-existing",
        action="store_true",
        help="Revalidate an existing strict preflight receipt instead of failing because --out exists.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        output = args.out.expanduser().resolve()
        if args.reuse_existing and output.is_file():
            if _is_migratable_unreadable_dependency_receipt(output):
                output.unlink()
                result = build_exavatar_preflight_strict_files(
                    dependency_root=args.dependency_root,
                    asset_root=args.asset_root,
                    reference_model_root=args.reference_model_root,
                    smplx_gender=args.smplx_gender,
                    output_path=output,
                    require_colmap=not args.no_colmap,
                )
            else:
                result = validate_exavatar_preflight_strict_file(
                    output,
                    dependency_root=args.dependency_root,
                    asset_root=args.asset_root,
                    reference_model_root=args.reference_model_root,
                    smplx_gender=args.smplx_gender,
                    require_colmap=not args.no_colmap,
                )
        else:
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
