from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_person_binding import (
    PhotorealPersonBindingError,
    write_photoreal_person_binding,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bind an accepted Photoreal V2 P3 result to one exact BodyRig Person/body "
            "lineage through the existing Stash performer source authority."
        )
    )
    parser.add_argument("--person-library", type=Path, required=True)
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--assembly-receipt", type=Path, required=True)
    parser.add_argument("--body-release-status", type=Path, required=True)
    parser.add_argument("--p3-physical-review", type=Path, required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)

    try:
        authority = write_photoreal_person_binding(
            args.out,
            person_library=args.person_library,
            person_id=args.person_id,
            assembly_receipt_path=args.assembly_receipt,
            body_release_status_path=args.body_release_status,
            p3_physical_runtime_review_path=args.p3_physical_review,
            bodyrig_revision=args.bodyrig_revision,
        )
    except PhotorealPersonBindingError as exc:
        print(f"BodyRig Photoreal Person binding: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "binding_id": authority["binding_id"],
                "person_id": authority["person_id"],
                "person_revision": authority["person_revision"],
                "body_id": authority["body_id"],
                "stash_performer_id": authority["stash_performer_id"],
                "photoreal_binding_authority": True,
                "m4_photoreal_integration_eligible": True,
                "production_activation": False,
                "output": str(args.out.expanduser().resolve()),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
