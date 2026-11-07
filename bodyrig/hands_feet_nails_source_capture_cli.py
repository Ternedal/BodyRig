from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .hands_feet_nails_source_capture import (
    HandsFeetNailsSourceCaptureError,
    capture_dir,
    prepare_source_capture,
)
from .storage import person_library
from . import json_io


def _read_json(path: str) -> dict:
    source = Path(path).expanduser().resolve()
    return json_io.read_json_object(
        source,
        error=HandsFeetNailsSourceCaptureError,
        unreadable=f"selection JSON is unreadable: {source}",
        not_object="selection JSON must contain an object",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Extract four source-grounded hand/foot closeups from the exact Stash media bound to a BodyRig body revision. "
            "This evidence is comparison-only and never activates production."
        )
    )
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--body-revision", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--selection-json", required=True)
    parser.add_argument("--ffmpeg-exe", default="ffmpeg")
    args = parser.parse_args(argv)

    try:
        receipt = prepare_source_capture(
            person_library(),
            args.person_id,
            body_revision=args.body_revision,
            bodyrig_revision=args.bodyrig_revision,
            selections=_read_json(args.selection_json),
            ffmpeg_exe=args.ffmpeg_exe,
        )
        root = capture_dir(
            person_library(),
            str(receipt["person_id"]),
            str(receipt["body_revision"]),
            str(receipt["capture_id"]),
        )
    except (HandsFeetNailsSourceCaptureError, OSError, ValueError) as exc:
        print(f"BodyRig hands/feet/nails source capture: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "capture_id": receipt["capture_id"],
                "person_id": receipt["person_id"],
                "body_revision": receipt["body_revision"],
                "source_manifest_sha256": receipt["source_manifest_sha256"],
                "capture_dir": str(root),
                "manifest": str(root / "source-capture.json"),
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
