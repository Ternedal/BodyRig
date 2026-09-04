from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_eye_runtime_fingerprint import (
    HighFidelityEyeRuntimeFingerprintError,
    read_fingerprint,
    write_fingerprint,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record/verify a canonical semantic fingerprint for the exact reviewed source-eye runtime."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("record", "verify"):
        item = sub.add_parser(name)
        item.add_argument("--preview-job-id", required=True)
        item.add_argument("--base-runtime-dir", required=True)
        item.add_argument("--iris-candidate-dir", required=True)
        item.add_argument("--source-eye-appearance-dir", required=True)
        item.add_argument("--reviewed-runtime-dir", required=True)
        if name == "record":
            item.add_argument("--bodyrig-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "record":
            value = write_fingerprint(
                args.preview_job_id,
                base_runtime_dir=args.base_runtime_dir,
                iris_candidate_dir=args.iris_candidate_dir,
                source_eye_appearance_dir=args.source_eye_appearance_dir,
                reviewed_runtime_dir=args.reviewed_runtime_dir,
                bodyrig_revision=args.bodyrig_revision,
            )
        else:
            value = read_fingerprint(
                args.preview_job_id,
                base_runtime_dir=args.base_runtime_dir,
                iris_candidate_dir=args.iris_candidate_dir,
                source_eye_appearance_dir=args.source_eye_appearance_dir,
                reviewed_runtime_dir=args.reviewed_runtime_dir,
            )
    except (OSError, HighFidelityEyeRuntimeFingerprintError) as exc:
        print(f"BodyRig eye runtime fingerprint: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "mode": args.command,
                "fingerprint_bodyrig_revision": value["fingerprintBodyrigRevision"],
                "fingerprint_path": value["fingerprintPath"],
                "candidate_package_sha256": value["candidatePackageSha256"],
                "review_vrm_sha256": value["reviewVrmSha256"],
                "fingerprint_sha256": value["fingerprintSha256"],
                "index_independent": value["indexIndependent"],
                "buffer_offset_independent": value["bufferOffsetIndependent"],
                "eyes_promotion_eligibility_verified": value["eyesPromotionEligibilityVerified"],
                "eye_component_authority": value["eyeComponentAuthority"],
                "package_mutation_performed": value["packageMutationPerformed"],
                "eyes_promoted": value["eyesPromoted"],
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
