from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_teacher_review_mapping import (
    PhotorealTeacherReviewMappingError,
    build_review_mapping_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record human semantic mapping from calibrated teacher renders to held-out review references without granting likeness acceptance."
    )
    parser.add_argument("--render-set", type=Path, required=True)
    parser.add_argument("--reference-catalog", type=Path, required=True)
    parser.add_argument("--selection-input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_review_mapping_files(
            args.render_set,
            args.reference_catalog,
            args.selection_input,
            args.out,
        )
    except PhotorealTeacherReviewMappingError as exc:
        print(f"BodyRig photoreal review mapping: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "format": result["format"],
        "version": result["version"],
        "performer_id": result["performer_id"],
        "selected_epoch_id": result["selected_epoch_id"],
        "mapping_count": result["mapping_count"],
        "semantic_view_mapping_complete": result["semantic_view_mapping_complete"],
        "reference_selection_complete": result["reference_selection_complete"],
        "reference_bytes_materialized": result["reference_bytes_materialized"],
        "likeness_review_complete": result["likeness_review_complete"],
        "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
        "production_activation": result["production_activation"],
    }, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
