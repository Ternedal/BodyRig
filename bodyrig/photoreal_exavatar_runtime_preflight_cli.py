from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_exavatar_runtime_preflight import PhotorealExAvatarRuntimePreflightError
from .photoreal_exavatar_runtime_preflight_strict import (
    PhotorealExAvatarRuntimePreflightStrictError,
    build_runtime_preflight_strict_file,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Verify pinned ExAvatar setup provenance, Python, CUDA and compiled runtime dependencies.")
    parser.add_argument("--workspace-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_runtime_preflight_strict_file(workspace_root=args.workspace_root, output_path=args.out)
    except (PhotorealExAvatarRuntimePreflightError, PhotorealExAvatarRuntimePreflightStrictError) as exc:
        print(f"BodyRig Photoreal ExAvatar runtime preflight: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "python_version": result["python_version"],
                "runtime_setup_provenance_verified": result["runtime_setup_provenance_verified"],
                "runtime_setup_sha256": result["runtime_setup_sha256"],
                "hand4whole_assets_sha256": result["hand4whole_assets_sha256"],
                "runtime_environment_ready": result["runtime_environment_ready"],
                "blocker_count": len(result["blockers"]),
                "blockers": result["blockers"],
                "cuda": result["cuda"],
                "pytorch3d_cuda_smoke_passed": result["pytorch3d_cuda_smoke_passed"],
                "gaussian_cuda_extension_available": result["gaussian_rasterizer"]["cuda_extension_available"],
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0 if result["runtime_environment_ready"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
