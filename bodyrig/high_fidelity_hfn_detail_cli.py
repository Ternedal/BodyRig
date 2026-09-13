from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_hfn_detail import HighFidelityHfnDetailError, prepare_hfn_detail


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bind source-grounded hands/feet/nails detail into the final high-fidelity continuation package."
    )
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--landmark-evidence", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)

    try:
        result = prepare_hfn_detail(
            args.preview_job_id,
            capture_id=args.capture_id,
            landmark_evidence_path=args.landmark_evidence,
            bodyrig_revision=args.bodyrig_revision,
        )
    except (OSError, HighFidelityHfnDetailError) as exc:
        print(f"BodyRig high-fidelity HFN detail: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "preview_job_id": result["preview_job_id"],
                "capture_id": result["capture_id"],
                "body_id": result["body_id"],
                "body_revision": result["body_revision"],
                "bodyrig_revision": result["bodyrig_revision"],
                "source_package_sha256": result["source_package_sha256"],
                "candidate_id": result["candidate_id"],
                "candidate_package_sha256": result["candidate_package_sha256"],
                "package_path": result["package_path"],
                "human_review_required": result["human_review_required"],
                "physical_acceptance_required": result["physical_acceptance_required"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
