from __future__ import annotations

import argparse
import sys

from .high_fidelity_hfn_review import HighFidelityHfnReviewError, write_review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record package-bound HFN human review for the exact detail-bearing high-fidelity candidate."
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--body-revision", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--render-manifest", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--quality-note", required=True)
    parser.add_argument("--confirm-detail-checklist", action="store_true")
    args = parser.parse_args(argv)

    try:
        result = write_review(
            args.output_dir,
            root=args.root,
            person_id=args.person_id,
            body_revision=args.body_revision,
            capture_id=args.capture_id,
            candidate_id=args.candidate_id,
            render_manifest_path=args.render_manifest,
            bodyrig_revision=args.bodyrig_revision,
            quality_note=args.quality_note,
            confirm_detail_checklist=args.confirm_detail_checklist,
        )
    except (OSError, HighFidelityHfnReviewError) as exc:
        print(f"BodyRig HFN human review: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "BodyRig HFN human review: PASS | "
        f"review={result['review_id']} | package={result['candidate_package_sha256']} | "
        "source-grounded=true | human-review-completed=true | production-activation=false"
    )
    print(f"HFN human-review receipt: {result['review_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
