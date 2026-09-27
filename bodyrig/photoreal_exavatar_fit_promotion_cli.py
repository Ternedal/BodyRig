from __future__ import annotations

import argparse
import json

from .photoreal_exavatar_preprocess import promote_diagnostic_smplx_fit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Promote a fully validated isolated ExAvatar fit into the workspace."
    )
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--camera-mode", required=True, choices=("virtual", "colmap"))
    parser.add_argument("--python", required=True, dest="python_executable")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = promote_diagnostic_smplx_fit(
        workspace_root=args.workspace_root,
        camera_mode=args.camera_mode,
        python_executable=args.python_executable,
    )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
