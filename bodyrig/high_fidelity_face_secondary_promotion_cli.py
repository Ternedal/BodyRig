from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_face_secondary_promotion import (
    HighFidelityFaceSecondaryPromotionError,
    read_promotion,
    write_promotion,
)


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preparation-dir", required=True)
    parser.add_argument("--runtime-dir", required=True)
    parser.add_argument("--render-dir", required=True)
    parser.add_argument("--human-review-dir", required=True)
    parser.add_argument("--source-package", required=True)
    parser.add_argument("--output-dir", required=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Promote exact reviewed face-secondary runtime into a new .mrbody package.")
    sub = parser.add_subparsers(dest="command", required=True)
    promote = sub.add_parser("promote")
    _common(promote)
    promote.add_argument("--bodyrig-revision", required=True)
    verify = sub.add_parser("verify")
    _common(verify)
    args = parser.parse_args(argv)
    try:
        if args.command == "promote":
            value = write_promotion(
                preparation_dir=args.preparation_dir,
                runtime_dir=args.runtime_dir,
                render_dir=args.render_dir,
                human_review_dir=args.human_review_dir,
                source_package_path=args.source_package,
                output_dir=args.output_dir,
                promotion_bodyrig_revision=args.bodyrig_revision,
            )
        else:
            value = read_promotion(
                preparation_dir=args.preparation_dir,
                runtime_dir=args.runtime_dir,
                render_dir=args.render_dir,
                human_review_dir=args.human_review_dir,
                source_package_path=args.source_package,
                output_dir=args.output_dir,
            )
    except (OSError, HighFidelityFaceSecondaryPromotionError) as exc:
        print(f"BodyRig face-secondary promotion: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
