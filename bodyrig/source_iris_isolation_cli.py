from __future__ import annotations

import argparse
import json
import sys

from .source_iris_isolation import SourceIrisIsolationError, build_candidate
from .source_iris_isolation_review import (
    CHECKLIST_FIELDS,
    SourceIrisIsolationReviewError,
    read_review,
    write_review,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create and review source-bound iris isolation authority.")
    sub = parser.add_subparsers(dest="command", required=True)

    candidate = sub.add_parser("candidate", help="Create review-only iris candidates from exact source eye crops.")
    candidate.add_argument("--source-eye-appearance-dir", required=True)
    candidate.add_argument("--output-dir", required=True)
    candidate.add_argument("--bodyrig-revision", required=True)
    for side in ("left", "right"):
        candidate.add_argument(f"--{side}-cx", required=True, type=int)
        candidate.add_argument(f"--{side}-cy", required=True, type=int)
        candidate.add_argument(f"--{side}-radius", required=True, type=int)

    review = sub.add_parser("review", help="Record explicit human iris-isolation review authority.")
    review.add_argument("--candidate-dir", required=True)
    review.add_argument("--source-eye-appearance-dir", required=True)
    review.add_argument("--bodyrig-revision", required=True)
    review.add_argument("--quality-note", required=True)
    review.add_argument("--confirm-iris-isolation-checklist", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "candidate":
            result = build_candidate(
                source_eye_appearance_dir=args.source_eye_appearance_dir,
                output_dir=args.output_dir,
                bodyrig_revision=args.bodyrig_revision,
                left_annotation={"cx": args.left_cx, "cy": args.left_cy, "radius": args.left_radius},
                right_annotation={"cx": args.right_cx, "cy": args.right_cy, "radius": args.right_radius},
            )
            payload = {
                "ok": True,
                "mode": "candidate",
                "candidate_path": result["candidatePath"],
                "left_path": result["leftPath"],
                "right_path": result["rightPath"],
                "bodyrig_revision": result["bodyrigRevision"],
                "iris_identity_isolated": False,
                "human_review_required": True,
                "eye_component_authority": False,
                "production_activation": False,
            }
        else:
            if not args.confirm_iris_isolation_checklist:
                raise SourceIrisIsolationReviewError(
                    "explicit --confirm-iris-isolation-checklist is required after reviewing both source eye crops and candidate boundaries"
                )
            result = write_review(
                candidate_dir=args.candidate_dir,
                source_eye_appearance_dir=args.source_eye_appearance_dir,
                bodyrig_revision=args.bodyrig_revision,
                checklist={field: True for field in CHECKLIST_FIELDS},
                quality_note=args.quality_note,
            )
            verified = read_review(
                candidate_dir=args.candidate_dir,
                source_eye_appearance_dir=args.source_eye_appearance_dir,
            )
            payload = {
                "ok": True,
                "mode": "review",
                "review_path": result["reviewPath"],
                "bodyrig_revision": verified["bodyrigRevision"],
                "iris_identity_isolated": True,
                "iris_appearance_status": verified["irisAppearanceStatus"],
                "eyes_promotion_eligible": False,
                "eye_component_authority": False,
                "production_activation": False,
            }
    except (OSError, SourceIrisIsolationError, SourceIrisIsolationReviewError) as exc:
        print(f"BodyRig source iris isolation: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
