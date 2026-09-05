from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .storage import person_library
from .wardrobe_release_authority import (
    WardrobeReleaseAuthorityError,
    release_authority_dir,
    write_release_authority,
)


def _read_json(path: str, label: str) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WardrobeReleaseAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise WardrobeReleaseAuthorityError(f"{label} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Finalize exact transitive M3 wardrobe authority without activating production.")
    parser.add_argument("--assembly-receipt", required=True)
    parser.add_argument("--body-release-status", required=True)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)
    try:
        assembly = _read_json(args.assembly_receipt, "Person assembly receipt")
        body_release = _read_json(args.body_release_status, "body release status")
        receipt = write_release_authority(
            person_library(),
            assembly_receipt=assembly,
            body_release_status=body_release,
            review_id=args.review_id,
            bodyrig_revision=args.bodyrig_revision,
        )
        root = release_authority_dir(person_library(), str(receipt["person_id"]), str(receipt["person_revision"]), str(receipt["release_id"]))
    except (WardrobeReleaseAuthorityError, OSError, ValueError) as exc:
        print(f"BodyRig finalized wardrobe authority: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "ok": True,
        "release_id": receipt["release_id"],
        "review_id": receipt["review_id"],
        "person_id": receipt["person_id"],
        "person_revision": receipt["person_revision"],
        "authority": str(root / "authority.json"),
        "production_activation": False,
    }, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
