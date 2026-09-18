from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_spatial_metadata_probe import (
    PhotorealSpatialMetadataProbeError,
    build_spatial_container_probe_files,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Probe build-private video containers for Spherical Video V2 / VR180 and legacy V1 metadata without "
            "granting deprojection or identity authority."
        )
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = build_spatial_container_probe_files(args.inventory, args.receipt, args.out)
    except (PhotorealSpatialMetadataProbeError, OSError) as exc:
        print(f"BodyRig spatial container probe: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "status": "PASS",
                "format": result["format"],
                "performer_id": result["performer_id"],
                "video_source_count": result["video_source_count"],
                "parsed_isobmff_count": result["parsed_isobmff_count"],
                "spherical_v2_source_count": result["spherical_v2_source_count"],
                "spherical_v1_source_count": result["spherical_v1_source_count"],
                "dual_v1_v2_source_count": result["dual_v1_v2_source_count"],
                "mesh_projection_source_count": result["mesh_projection_source_count"],
                "camm_source_count": result["camm_source_count"],
                "size_mismatch_count": result["size_mismatch_count"],
                "diagnostic_only": result["diagnostic_only"],
                "deprojection_authority": result["deprojection_authority"],
                "production_activation": result["production_activation"],
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
