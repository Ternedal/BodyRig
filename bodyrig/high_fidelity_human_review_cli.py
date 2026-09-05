from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .high_fidelity_human_review import (
    CHECKLIST_FIELDS,
    HighFidelityHumanReviewError,
    read_review,
    review_path,
    write_review,
)
from .storage import body_library

_BODY_ID = re.compile(r"^[A-Za-z0-9._-]{3,160}$")


def _package_for_body_id(body_id: str) -> Path:
    clean = str(body_id or "").strip()
    if not _BODY_ID.fullmatch(clean):
        raise HighFidelityHumanReviewError("body id is not canonical")
    return body_library() / f"{clean}.mrbody"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Record a create-only human high-fidelity review for one exact installed BodyRig package. "
            "All component gates must already be complete; this receipt never activates production by itself."
        )
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--body-id", help="Canonical installed BodyRig body id.")
    source.add_argument("--package", help="Exact .mrbody package path.")
    parser.add_argument(
        "--confirm-quality-checklist",
        action="store_true",
        help=(
            "Explicitly confirm source identity, anatomy, skin, hair, eyes, face-secondary, "
            "full-body multiview and face close-up review."
        ),
    )
    parser.add_argument("--quality-note", required=True, help="Operator's physical high-fidelity review note.")
    args = parser.parse_args(argv)

    created_path: Path | None = None
    try:
        if not args.confirm_quality_checklist:
            raise HighFidelityHumanReviewError(
                "high-fidelity human review requires explicit --confirm-quality-checklist"
            )
        package = (
            _package_for_body_id(args.body_id)
            if args.body_id is not None
            else Path(args.package).expanduser().resolve()
        )
        receipt = write_review(
            package,
            checklist={field: True for field in CHECKLIST_FIELDS},
            quality_note=args.quality_note,
        )
        created_path = review_path(package, package_sha256=receipt["package_sha256"])
        verified = read_review(package)
        if verified != receipt:
            raise HighFidelityHumanReviewError("written high-fidelity human review did not verify byte-for-byte")
        output = {
            "ok": True,
            "body_id": receipt["body_id"],
            "package_sha256": receipt["package_sha256"],
            "component_state_sha256": receipt["component_state_sha256"],
            "policy_revision": receipt["policy_revision"],
            "review_path": str(created_path),
            "production_activation": False,
        }
    except (HighFidelityHumanReviewError, OSError) as exc:
        if created_path is not None:
            try:
                created_path.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                print(
                    f"BodyRig high-fidelity human review: cleanup failed for {created_path}: {cleanup_exc}",
                    file=sys.stderr,
                )
        print(f"BodyRig high-fidelity human review: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
