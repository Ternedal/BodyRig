from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .high_fidelity_human_review import HighFidelityHumanReviewError, archive_invalid_review
from .high_fidelity_physical_acceptance import HighFidelityPhysicalAcceptanceError, physical_acceptance_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Archive one invalid create-only high-fidelity human-review receipt without deleting its bytes, "
            "so the exact package can receive a new explicit review before fresh Gate A."
        )
    )
    parser.add_argument("--preview-job-id", required=True, help="Exact high-fidelity preview job id.")
    parser.add_argument("--package", required=True, type=Path, help="Exact promoted .mrbody package path.")
    args = parser.parse_args(argv)

    try:
        acceptance = physical_acceptance_dir(args.preview_job_id)
        if acceptance.exists():
            raise HighFidelityHumanReviewError(
                "human-review recovery is disabled after fresh Gate A exists; frozen acceptance authority must be audited instead"
            )
        result = archive_invalid_review(args.package)
    except (HighFidelityHumanReviewError, HighFidelityPhysicalAcceptanceError, OSError) as exc:
        print(f"BodyRig high-fidelity human review recovery: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
