from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_frame_index import PhotorealFrameIndexError
from .photoreal_frame_index_readback_authority import build_frame_index_files_strict


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate core-authorized photoreal frame observations against the byte-bound dataset plan."
        )
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument(
        "--authorized-observations",
        "--observations",
        dest="observations",
        type=Path,
        required=True,
        help="Core-authorized observations from bodyrig-photoreal-frame-authorize-identity.",
    )
    parser.add_argument("--out", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = build_frame_index_files_strict(args.plan, args.receipt, args.observations, args.out)
    except PhotorealFrameIndexError as exc:
        print(f"BodyRig photoreal frame index: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "analyzer": result["analyzer"],
                "analyzer_revision": result["analyzer_revision"],
                "analyzer_model_set_sha256": result["analyzer_model_set_sha256"],
                "observation_count": result["observation_count"],
                "eligible_train_observation_count": result["eligible_train_observation_count"],
                "eligible_evaluation_observation_count": result["eligible_evaluation_observation_count"],
                "cross_split_detected_near_duplicate_count": result["cross_split_detected_near_duplicate_count"],
                "cross_split_quarantined_train_observation_count": result["cross_split_quarantined_train_observation_count"],
                "cross_split_near_duplicate_count": result["cross_split_near_duplicate_count"],
                "held_out_view_coverage_missing": result["held_out_view_coverage_missing"],
                "teacher_training_authorized": result["teacher_training_authorized"],
                "training_blockers": result["training_blockers"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0 if result["teacher_training_authorized"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
