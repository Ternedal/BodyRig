from __future__ import annotations

import argparse
import sys

from .hands_feet_nails_detail_candidate import (
    HandsFeetNailsDetailCandidateError,
    build_detail_candidate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Create a source-grounded hands/feet/nails detail-bearing .mrbody candidate for downstream M2 review."
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--body-revision", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--uv-evidence", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    try:
        result = build_detail_candidate(
            args.root,
            args.person_id,
            body_revision=args.body_revision,
            capture_id=args.capture_id,
            uv_evidence_path=args.uv_evidence,
            package_path=args.package,
            bodyrig_revision=args.bodyrig_revision,
        )
    except (OSError, HandsFeetNailsDetailCandidateError) as exc:
        print(f"BodyRig HFN detail candidate: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "BodyRig HFN detail candidate: PASS | "
        f"candidate={result['candidate_id']} | package={result['candidate_package_sha256']} | "
        "source-grounded=true | geometry-modified=false | texture-modified=true | "
        "human-review-required=true | production-activation=false"
    )
    print(f"HFN detail candidate package: {result['package_path']}")
    print(f"HFN detail candidate receipt: {result['receipt_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
