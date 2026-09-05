from __future__ import annotations

import argparse
import json
import sys

from .source_iris_review_runtime import SourceIrisReviewRuntimeError, build_reviewed_runtime, read_reviewed_runtime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bind reviewed source iris authority to an unchanged hair+eye review VRM.")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("build", "verify"):
        item = sub.add_parser(name)
        item.add_argument("--base-runtime-dir", required=True)
        item.add_argument("--iris-candidate-dir", required=True)
        item.add_argument("--source-eye-appearance-dir", required=True)
        item.add_argument("--reviewed-runtime-dir", required=True)
        if name == "build":
            item.add_argument("--bodyrig-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_reviewed_runtime(
                base_runtime_dir=args.base_runtime_dir,
                iris_candidate_dir=args.iris_candidate_dir,
                source_eye_appearance_dir=args.source_eye_appearance_dir,
                bodyrig_revision=args.bodyrig_revision,
                output_dir=args.reviewed_runtime_dir,
            )
        else:
            result = read_reviewed_runtime(
                base_runtime_dir=args.base_runtime_dir,
                iris_candidate_dir=args.iris_candidate_dir,
                source_eye_appearance_dir=args.source_eye_appearance_dir,
                reviewed_runtime_dir=args.reviewed_runtime_dir,
            )
    except (OSError, SourceIrisReviewRuntimeError) as exc:
        print(f"BodyRig source iris reviewed runtime: FAIL: {exc}", file=sys.stderr)
        return 1
    payload = {
        "ok": True,
        "mode": args.command,
        "bodyrig_revision": result["bodyrigRevision"],
        "base_review_vrm_sha256": result["baseReviewVrmSha256"],
        "reviewed_vrm_sha256": result["reviewedVrmSha256"],
        "reviewed_vrm_path": result["reviewedVrmPath"],
        "review_receipt_path": result["reviewReceiptPath"],
        "runtime_bytes_unchanged": result["runtimeBytesUnchanged"],
        "source_eye_pixels_unchanged": result["sourceEyePixelsUnchanged"],
        "iris_identity_isolated": result["irisIdentityIsolated"],
        "iris_appearance_status": result["irisAppearanceStatus"],
        "eyes_promotion_eligible": result["eyesPromotionEligible"],
        "eye_component_authority": result["eyeComponentAuthority"],
        "production_activation": result["productionActivation"],
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
