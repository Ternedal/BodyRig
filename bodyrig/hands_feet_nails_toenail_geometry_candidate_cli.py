from __future__ import annotations

import argparse
import sys

from .hands_feet_nails_detail_candidate import HandsFeetNailsDetailCandidateError, read_detail_candidate
from .hands_feet_nails_toenail_geometry_candidate import (
    HandsFeetNailsToenailGeometryError,
    build_toenail_geometry_candidate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create source-bound additive toenail plate geometry on top of an exact HFN "
            "fingernail-geometry candidate."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--body-revision", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    expected_revision = str(args.bodyrig_revision).strip().lower()
    try:
        detail = read_detail_candidate(
            args.root,
            args.person_id,
            body_revision=args.body_revision,
            capture_id=args.capture_id,
            candidate_id=args.candidate_id,
        )
        if str(detail.get("bodyrig_revision") or "").strip().lower() != expected_revision:
            raise HandsFeetNailsToenailGeometryError(
                "HFN detail candidate was produced by a different BodyRig revision"
            )
        result = build_toenail_geometry_candidate(
            args.root,
            args.person_id,
            body_revision=args.body_revision,
            capture_id=args.capture_id,
            candidate_id=args.candidate_id,
        )
    except (OSError, HandsFeetNailsDetailCandidateError, HandsFeetNailsToenailGeometryError) as exc:
        print(f"BodyRig HFN toenail geometry candidate: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "BodyRig HFN toenail geometry candidate: PASS | "
        f"candidate={result['candidate_id']} | package={result['geometry_package_sha256']} | "
        f"plates={result['plate_count']} | geometry-modified=true | texture-modified=false | "
        "middle-toe-landmarks-observed=false | source-grounded=true | "
        "human-review-required=true | production-activation=false"
    )
    print(f"HFN toenail geometry package: {result['package_path']}")
    print(f"HFN toenail geometry receipt: {result['receipt_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
