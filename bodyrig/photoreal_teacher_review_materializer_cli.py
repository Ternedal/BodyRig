from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_teacher_review_materializer import (
    PhotorealTeacherReviewMaterializerError,
    run_external_materializer_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize selected held-out Photoreal review frames with exact P0 OpenCV decode/hash semantics."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--reference-catalog", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_external_materializer_files(
            args.config,
            args.mapping,
            args.reference_catalog,
            args.workspace,
        )
    except PhotorealTeacherReviewMaterializerError as exc:
        print(f"BodyRig held-out reference materialization: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "format": result["format"],
        "version": result["version"],
        "performer_id": result["performer_id"],
        "selected_epoch_id": result["selected_epoch_id"],
        "source_count": result["source_count"],
        "sample_count": result["sample_count"],
        "all_source_hashes_verified": result["all_source_hashes_verified"],
        "all_frame_hashes_verified": result["all_frame_hashes_verified"],
        "photoreal_acceptance_authority": result["photoreal_acceptance_authority"],
        "production_activation": result["production_activation"],
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
