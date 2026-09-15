from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_exavatar_hand4whole_stage import (
    PhotorealExAvatarHand4WholeStageError,
    stage_hand4whole_assets,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stage strict Hand4Whole human-model assets inside an isolated ExAvatar workspace.")
    parser.add_argument("--workspace-root", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = stage_hand4whole_assets(workspace_root=args.workspace_root)
    except PhotorealExAvatarHand4WholeStageError as exc:
        print(f"BodyRig ExAvatar Hand4Whole assets: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "smplx_gender": result["smplx_gender"],
                "required_asset_count": result["required_asset_count"],
                "hand4whole_assets_sha256": result["hand4whole_assets_sha256"],
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                "production_activation": result["production_activation"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
