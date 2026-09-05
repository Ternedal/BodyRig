from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_face_secondary_preview import (
    HighFidelityFaceSecondaryPreviewError,
    finalize_preview,
    prepare,
    read_preview,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare/finalize/verify exact face-secondary Windows review evidence.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_cmd = sub.add_parser("prepare")
    prepare_cmd.add_argument("--package", required=True)
    prepare_cmd.add_argument("--runtime-dir", required=True)
    prepare_cmd.add_argument("--output-dir", required=True)
    prepare_cmd.add_argument("--bodyrig-revision", required=True)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--preparation-dir", required=True)
    finalize.add_argument("--runtime-dir", required=True)
    finalize.add_argument("--render-dir", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--preparation-dir", required=True)
    verify.add_argument("--runtime-dir", required=True)
    verify.add_argument("--render-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            value = prepare(args.package, args.runtime_dir, args.output_dir, bodyrig_revision=args.bodyrig_revision)
        elif args.command == "finalize":
            value = finalize_preview(args.preparation_dir, args.runtime_dir, args.render_dir)
        else:
            value = read_preview(args.preparation_dir, args.runtime_dir, args.render_dir)
    except (OSError, HighFidelityFaceSecondaryPreviewError) as exc:
        print(f"BodyRig face-secondary Windows preview: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
