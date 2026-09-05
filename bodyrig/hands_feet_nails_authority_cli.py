from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .hands_feet_nails_authority import (
    CHECKLIST_FIELDS,
    HandsFeetNailsAuthorityError,
    authority_dir,
    write_authority,
)
from .storage import person_library


def _read_json(path: str, label: str) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise HandsFeetNailsAuthorityError(f"{label} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Record a create-only operator-supplied hands/feet/nails authority bound to exact source closeups, "
            "exact BodyRig package bytes and exact Unity detail renders. The authority remains non-activating."
        )
    )
    parser.add_argument("--assembly-receipt", required=True)
    parser.add_argument("--body-release-status", required=True)
    parser.add_argument("--source-capture-id", required=True)
    parser.add_argument("--render-manifest", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--confirm-detail-checklist", action="store_true")
    parser.add_argument("--quality-note", required=True)
    args = parser.parse_args(argv)

    try:
        if not args.confirm_detail_checklist:
            raise HandsFeetNailsAuthorityError(
                "hands/feet/nails authority requires explicit --confirm-detail-checklist"
            )
        assembly = _read_json(args.assembly_receipt, "Person assembly receipt")
        body_release = _read_json(args.body_release_status, "body release status")
        receipt = write_authority(
            person_library(),
            assembly_receipt=assembly,
            body_release_status=body_release,
            source_capture_id=args.source_capture_id,
            render_manifest_path=args.render_manifest,
            bodyrig_revision=args.bodyrig_revision,
            checklist={field: True for field in CHECKLIST_FIELDS},
            quality_note=args.quality_note,
        )
        root = authority_dir(
            person_library(),
            str(receipt["person_id"]),
            str(receipt["person_revision"]),
            str(receipt["review_id"]),
        )
    except (HandsFeetNailsAuthorityError, OSError, ValueError) as exc:
        print(f"BodyRig hands/feet/nails authority: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "review_id": receipt["review_id"],
                "person_id": receipt["person_id"],
                "person_revision": receipt["person_revision"],
                "body_revision": receipt["body_revision"],
                "body_package_sha256": receipt["body_package_sha256"],
                "authority": str(root / "authority.json"),
                "source_grounded": True,
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
