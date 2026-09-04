from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_eye_promotion import HighFidelityEyePromotionError, read_promotion, write_promotion


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--candidate-package", required=True)
    parser.add_argument("--target-package", required=True)
    parser.add_argument("--base-runtime-dir", required=True)
    parser.add_argument("--iris-candidate-dir", required=True)
    parser.add_argument("--source-eye-appearance-dir", required=True)
    parser.add_argument("--reviewed-runtime-dir", required=True)
    parser.add_argument("--eye-runtime-dir", required=True)
    parser.add_argument("--bridge-script-sha256", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Materialize a fingerprint-matched eye stage into a new .mrbody package.")
    sub = parser.add_subparsers(dest="command", required=True)
    promote = sub.add_parser("promote")
    _add_common(promote)
    promote.add_argument("--promotion-bodyrig-revision", required=True)
    verify = sub.add_parser("verify")
    _add_common(verify)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    common = dict(
        candidate_package_path=args.candidate_package,
        target_package_path=args.target_package,
        base_runtime_dir=args.base_runtime_dir,
        iris_candidate_dir=args.iris_candidate_dir,
        source_eye_appearance_dir=args.source_eye_appearance_dir,
        reviewed_runtime_dir=args.reviewed_runtime_dir,
        eye_runtime_dir=args.eye_runtime_dir,
        bridge_script_sha256=args.bridge_script_sha256,
    )
    try:
        if args.command == "promote":
            value = write_promotion(
                args.preview_job_id,
                promotion_bodyrig_revision=args.promotion_bodyrig_revision,
                **common,
            )
        else:
            value = read_promotion(args.preview_job_id, **common)
    except (OSError, HighFidelityEyePromotionError) as exc:
        print(f"BodyRig eye promotion: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "mode": args.command,
                "package_path": value["packagePath"],
                "receipt_path": value["receiptPath"],
                "promoted_package_sha256": value["promotedPackageSha256"],
                "promoted_avatar_sha256": value["promotedAvatarSha256"],
                "source_candidate_package_sha256": value["sourceCandidatePackageSha256"],
                "destination_source_package_sha256": value["destinationSourcePackageSha256"],
                "reviewed_eye_fingerprint_sha256": value["reviewedEyeFingerprintSha256"],
                "hair_complete_preserved": value["hairCompletePreserved"],
                "components_before": value["componentsBefore"],
                "components_after": value["componentsAfter"],
                "source_hair_runtime_imported": value["sourceHairRuntimeImported"],
                "production_activation": value["productionActivation"],
            },
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
