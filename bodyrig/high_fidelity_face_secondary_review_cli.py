from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_face_secondary_review import (
    CHECKLIST_FIELDS,
    HighFidelityFaceSecondaryReviewError,
    read_review,
    write_review,
)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preparation-dir", required=True)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--output-dir", required=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Record/verify exact face-secondary human review authority.")
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record")
    _add_common(record)
    record.add_argument("--bodyrig-revision", required=True)
    record.add_argument("--quality-note", required=True)
    for field in CHECKLIST_FIELDS:
        record.add_argument("--" + field.replace("_", "-"), action="store_true")
    verify = sub.add_parser("verify")
    _add_common(verify)
    args = parser.parse_args(argv)

    try:
        if args.command == "record":
            checklist = {field: bool(getattr(args, field)) for field in CHECKLIST_FIELDS}
            value = write_review(
                args.preparation_dir,
                args.runtime_dir,
                args.render_dir,
                args.output_dir,
                bodyrig_revision=args.bodyrig_revision,
                checklist=checklist,
                quality_note=args.quality_note,
            )
        else:
            value = read_review(args.preparation_dir, args.runtime_dir, args.render_dir, args.output_dir)
    except (OSError, HighFidelityFaceSecondaryReviewError) as exc:
        print(f"BodyRig face-secondary human review: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
