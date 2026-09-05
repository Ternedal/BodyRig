from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .storage import person_library
from .wardrobe_source_capture import WardrobeSourceCaptureError, capture_dir, prepare_source_capture


def _read_json(path: str) -> dict:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WardrobeSourceCaptureError(f"wardrobe selection JSON is unreadable: {source}") from exc
    if not isinstance(value, dict) or set(value) != {"views", "garments"}:
        raise WardrobeSourceCaptureError("wardrobe selection JSON requires exactly views and garments")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare exact source-grounded wardrobe presentation views and inventory.")
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--body-revision", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--selection-json", required=True)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args(argv)

    try:
        selection = _read_json(args.selection_json)
        receipt = prepare_source_capture(
            person_library(),
            args.person_id,
            body_revision=args.body_revision,
            bodyrig_revision=args.bodyrig_revision,
            views=selection["views"],
            garments=selection["garments"],
            ffmpeg_exe=args.ffmpeg,
        )
        root = capture_dir(person_library(), receipt["person_id"], receipt["body_revision"], receipt["capture_id"])
    except (WardrobeSourceCaptureError, OSError, ValueError) as exc:
        print(f"BodyRig wardrobe source capture: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "ok": True,
        "capture_id": receipt["capture_id"],
        "person_id": receipt["person_id"],
        "body_revision": receipt["body_revision"],
        "source_manifest_sha256": receipt["source_manifest_sha256"],
        "garment_count": len(receipt["garments"]),
        "footwear_present": receipt["footwear_present"],
        "capture_dir": str(root),
        "production_activation": False,
    }, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
