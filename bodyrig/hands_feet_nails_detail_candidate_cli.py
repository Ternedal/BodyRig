from __future__ import annotations

import argparse
import json
import sys

from .hands_feet_nails_detail_candidate import (
    HandsFeetNailsDetailCandidateError,
    write_detail_candidate,
)
from .storage import person_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a comparison-only hands/feet/nails detail-bearing .mrbody candidate from exact Person/body-bound "
            "M2 landmark evidence. This command never grants human-review or production authority."
        )
    )
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--body-revision", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--landmark-bodyrig-revision", required=True)
    parser.add_argument("--source-package", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    try:
        result = write_detail_candidate(
            person_library(),
            args.person_id,
            body_revision=args.body_revision,
            capture_id=args.capture_id,
            landmark_bodyrig_revision=args.landmark_bodyrig_revision,
            source_package_path=args.source_package,
            output_dir=args.output_dir,
            candidate_bodyrig_revision=args.bodyrig_revision,
        )
    except (OSError, ValueError, HandsFeetNailsDetailCandidateError) as exc:
        print(f"BodyRig HFN detail candidate: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "person_id": result["person_id"],
                "body_revision": result["body_revision"],
                "capture_id": result["capture_id"],
                "candidate_bodyrig_revision": result["candidate_bodyrig_revision"],
                "source_package_sha256": result["source_package_sha256"],
                "candidate_package_sha256": result["candidate_package_sha256"],
                "package_path": result["package_path"],
                "receipt_path": result["receipt_path"],
                "geometry_mutation_performed": False,
                "comparison_only": True,
                "human_review_required": True,
                "production_activation": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
