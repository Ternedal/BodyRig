from __future__ import annotations

import argparse
import sys

from .hands_feet_nails_uv_domain_evidence import (
    HandsFeetNailsUvDomainEvidenceError,
    derive_uv_domain_evidence,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive exact package-bound hands/feet/nails UV-domain evidence from the canonical skinned BodyRig mesh."
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--body-revision", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--landmark-evidence", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    try:
        result = derive_uv_domain_evidence(
            args.root,
            args.person_id,
            body_revision=args.body_revision,
            capture_id=args.capture_id,
            landmark_evidence_path=args.landmark_evidence,
            package_path=args.package,
            uv_bodyrig_revision=args.bodyrig_revision,
        )
    except (OSError, HandsFeetNailsUvDomainEvidenceError) as exc:
        print(f"BodyRig HFN UV domain evidence: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "BodyRig HFN UV domain evidence: PASS | "
        f"person={result['person_id']} | body={result['body_revision']} | capture={result['capture_id']} | "
        f"package={result['package_sha256']} | geometry-modified=false | texture-modified=false | package-authority=false"
    )
    print(f"HFN UV domain evidence: {result['manifest']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
