from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_teacher_review_renders import (
    PhotorealTeacherReviewRenderError,
    build_teacher_review_render_set_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bind exact Photoreal V2 teacher review renders to their calibrated camera orbit without assigning semantic view labels."
    )
    parser.add_argument("--teacher-manifest", type=Path, required=True)
    parser.add_argument("--teacher-output-root", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_teacher_review_render_set_files(
            args.teacher_manifest,
            args.teacher_output_root,
            args.out,
        )
    except PhotorealTeacherReviewRenderError as exc:
        print(f"BodyRig photoreal teacher review renders: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "selected_epoch_id": result["selected_epoch_id"],
                "render_count": result["render_count"],
                "render_bytes_verified": result["render_bytes_verified"],
                "camera_geometry_authority": result["camera_geometry_authority"],
                "semantic_view_authority": result["semantic_view_authority"],
                "human_semantic_view_mapping_required": result["human_semantic_view_mapping_required"],
                "held_out_reference_binding_present": result["held_out_reference_binding_present"],
                "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
