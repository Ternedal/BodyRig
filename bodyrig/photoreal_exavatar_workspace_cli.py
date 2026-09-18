from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_exavatar_workspace import (
    PhotorealExAvatarWorkspaceError,
    build_exavatar_workspace_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build an isolated, hash-bound ExAvatar benchmark workspace.")
    parser.add_argument("--materialized-dataset-dir", type=Path, required=True)
    parser.add_argument("--materialization-receipt", type=Path, required=True)
    parser.add_argument("--strict-preflight", type=Path, required=True)
    parser.add_argument("--dependency-root", type=Path, required=True)
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--reference-model-root", type=Path, required=True)
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--smplx-gender", choices=("female", "male", "neutral"), required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_exavatar_workspace_files(
            materialized_dataset_dir=args.materialized_dataset_dir,
            materialization_receipt_path=args.materialization_receipt,
            strict_preflight_path=args.strict_preflight,
            dependency_root=args.dependency_root,
            asset_root=args.asset_root,
            reference_model_root=args.reference_model_root,
            workspace_root=args.workspace_root,
            smplx_gender=args.smplx_gender,
        )
    except PhotorealExAvatarWorkspaceError as exc:
        print(f"BodyRig Photoreal ExAvatar workspace: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "subject_id": result["subject_id"],
                "smplx_gender": result["smplx_gender"],
                "dataset": result["dataset"],
                "frame_count": result["frame_count"],
                "workspace_sha256": result["workspace_sha256"],
                "held_out_evaluation_disclosed": result["held_out_evaluation_disclosed"],
                "dependency_root_modified": result["dependency_root_modified"],
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
