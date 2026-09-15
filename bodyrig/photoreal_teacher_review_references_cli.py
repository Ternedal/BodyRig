from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_teacher_review_references import (
    PhotorealTeacherReviewReferenceError,
    build_held_out_reference_catalog_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a build-private held-out Photoreal V2 reference catalog that remains undisclosed to teacher processes."
    )
    parser.add_argument("--teacher-input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_held_out_reference_catalog_files(args.teacher_input, args.out)
    except PhotorealTeacherReviewReferenceError as exc:
        print(f"BodyRig photoreal held-out references: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "selected_epoch_id": result["selected_epoch_id"],
                "held_out_source_count": result["held_out_source_count"],
                "held_out_observation_count": result["held_out_observation_count"],
                "required_coverage": result["required_coverage"],
                "teacher_process_disclosure": result["teacher_process_disclosure"],
                "reference_bytes_materialized": result["reference_bytes_materialized"],
                "reference_frame_hashes_verified": result["reference_frame_hashes_verified"],
                "human_reference_selection_required": result["human_reference_selection_required"],
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
