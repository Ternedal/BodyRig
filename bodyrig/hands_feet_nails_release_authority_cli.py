from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .hands_feet_nails_release_authority import (
    HandsFeetNailsReleaseAuthorityError,
    release_authority_dir,
    write_release_authority,
)
from .storage import person_library


def _read_json(path: str, label: str) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandsFeetNailsReleaseAuthorityError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise HandsFeetNailsReleaseAuthorityError(f"{label} must contain a JSON object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Finalize an operator-supplied M2 hands/feet/nails review by binding it to the exact "
            "comparison-authority-backed Unity render attempt. This remains non-activating."
        )
    )
    parser.add_argument("--assembly-receipt", required=True)
    parser.add_argument("--body-release-status", required=True)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--render-authority", required=True)
    args = parser.parse_args(argv)

    try:
        assembly = _read_json(args.assembly_receipt, "Person assembly receipt")
        body_release = _read_json(args.body_release_status, "body release status")
        receipt = write_release_authority(
            person_library(),
            assembly_receipt=assembly,
            body_release_status=body_release,
            review_id=args.review_id,
            render_authority_path=args.render_authority,
        )
        root = release_authority_dir(
            person_library(),
            str(receipt["person_id"]),
            str(receipt["person_revision"]),
            str(receipt["release_id"]),
        )
    except (HandsFeetNailsReleaseAuthorityError, OSError, ValueError) as exc:
        print(f"BodyRig hands/feet/nails finalization: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "release_id": receipt["release_id"],
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
