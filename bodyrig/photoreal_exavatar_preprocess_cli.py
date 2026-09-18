from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .photoreal_exavatar_hand4whole_stage import (
    PhotorealExAvatarHand4WholeStageError,
    validate_hand4whole_assets_receipt,
)
from .photoreal_exavatar_preprocess import (
    PhotorealExAvatarPreprocessError,
    build_preprocess_plan,
    run_preprocess,
)

UPSTREAM_SMOOTH_WINDOW = 9


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plan or run staged ExAvatar preprocessing inside an isolated BodyRig workspace.")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--camera-mode", choices=("colmap", "virtual"), required=True)
    parser.add_argument("--python", required=True, help="Absolute ExAvatar benchmark Python executable")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--plan-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    return parser


def _guard_plan(plan: dict[str, object], python_executable: str) -> None:
    if int(plan.get("frame_count") or 0) < UPSTREAM_SMOOTH_WINDOW:
        raise PhotorealExAvatarPreprocessError(
            f"ExAvatar benchmark has fewer than {UPSTREAM_SMOOTH_WINDOW} authorized frames; "
            "the pinned upstream smoothing window cannot run without changing benchmark semantics"
        )
    if not os.path.isabs(python_executable):
        raise PhotorealExAvatarPreprocessError("ExAvatar Python executable must be an absolute path")
    path = Path(python_executable)
    if not path.is_file():
        raise PhotorealExAvatarPreprocessError(f"ExAvatar Python executable not found: {path}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        hand4whole = validate_hand4whole_assets_receipt(workspace_root=args.workspace_root)
        plan = build_preprocess_plan(
            workspace_root=args.workspace_root,
            camera_mode=args.camera_mode,
            python_executable=args.python,
        )
        if hand4whole.get("workspace_sha256") != plan.get("workspace_sha256"):
            raise PhotorealExAvatarPreprocessError("Hand4Whole asset receipt belongs to different ExAvatar workspace")
        _guard_plan(plan, args.python)
        result = plan if args.plan_only else run_preprocess(
            workspace_root=args.workspace_root,
            camera_mode=args.camera_mode,
            python_executable=args.python,
        )
    except (PhotorealExAvatarPreprocessError, PhotorealExAvatarHand4WholeStageError) as exc:
        print(f"BodyRig Photoreal ExAvatar preprocess: FAIL: {exc}", file=sys.stderr)
        return 1

    summary = {
        "format": result["format"],
        "version": result["version"],
        "workspace_sha256": result["workspace_sha256"],
        "hand4whole_assets_sha256": hand4whole["hand4whole_assets_sha256"],
        "camera_mode": plan["camera_mode"],
        "frame_count": plan["frame_count"],
        "smplx_gender": plan["smplx_gender"],
        "plan_only": bool(args.plan_only),
        "preprocessing_complete": bool(result.get("preprocessing_complete", False)),
        "photoreal_acceptance_authority": False,
        "production_activation": False,
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
