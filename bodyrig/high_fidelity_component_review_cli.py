from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .high_fidelity_component_review import (
    CHECKLIST_FIELDS,
    HighFidelityComponentReviewError,
    read_review,
    review_path,
    write_review,
)

_JOB_ID = re.compile(r"^hfpreview-[0-9a-f]{32}$")
_REVISION = re.compile(r"^[0-9a-f]{40}$")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Record a create-only visual component review for one exact succeeded high-fidelity preview job. "
            "The v1 receipt can make anatomy promotion-eligible, but hair still requires deformation review and "
            "eyes still require iris authority. It never activates production."
        )
    )
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--confirm-visual-checklist", action="store_true")
    parser.add_argument("--quality-note", required=True)
    args = parser.parse_args(argv)

    created_path: Path | None = None
    try:
        job_id = str(args.preview_job_id or "").strip().lower()
        revision = str(args.bodyrig_revision or "").strip().lower()
        if not _JOB_ID.fullmatch(job_id):
            raise HighFidelityComponentReviewError("preview job id is not canonical")
        if not _REVISION.fullmatch(revision):
            raise HighFidelityComponentReviewError("BodyRig checkout revision is not canonical")
        if not args.confirm_visual_checklist:
            raise HighFidelityComponentReviewError(
                "component visual review requires explicit --confirm-visual-checklist"
            )

        receipt = write_review(
            job_id,
            bodyrig_revision=revision,
            checklist={field: True for field in CHECKLIST_FIELDS},
            quality_note=args.quality_note,
        )
        created_path = review_path(job_id, review_vrm_sha256=receipt["review_vrm_sha256"])
        verified = read_review(job_id)
        if verified != receipt:
            raise HighFidelityComponentReviewError("written component visual review did not verify byte-for-byte")
        output = {
            "ok": True,
            "preview_job_id": receipt["preview_job_id"],
            "bodyrig_revision": receipt["bodyrig_revision"],
            "candidate_package_sha256": receipt["candidate_package_sha256"],
            "review_vrm_sha256": receipt["review_vrm_sha256"],
            "promotion_eligibility": receipt["promotion_eligibility"],
            "review_outcome": receipt["review_outcome"],
            "review_path": str(created_path),
            "production_activation": False,
        }
    except (HighFidelityComponentReviewError, OSError) as exc:
        if created_path is not None:
            try:
                created_path.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                print(
                    f"BodyRig component visual review: cleanup failed for {created_path}: {cleanup_exc}",
                    file=sys.stderr,
                )
        print(f"BodyRig component visual review: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
