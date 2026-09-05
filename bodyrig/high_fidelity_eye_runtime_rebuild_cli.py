from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_eye_runtime_rebuild import (
    HighFidelityEyeRuntimeRebuildError,
    finalize_rebuild,
    prepare_rebuild,
    read_rebuild,
)


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--package", required=True)
    parser.add_argument("--base-runtime-dir", required=True)
    parser.add_argument("--iris-candidate-dir", required=True)
    parser.add_argument("--source-eye-appearance-dir", required=True)
    parser.add_argument("--reviewed-runtime-dir", required=True)
    parser.add_argument("--staging-dir", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare/finalize/verify a fingerprint-matched eye-only runtime rebuild.")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    _add_common(prepare)
    prepare.add_argument("--bodyrig-revision", required=True)
    finalize = sub.add_parser("finalize")
    _add_common(finalize)
    finalize.add_argument("--bodyrig-revision", required=True)
    finalize.add_argument("--bridge-script-sha256", required=True)
    verify = sub.add_parser("verify")
    _add_common(verify)
    verify.add_argument("--bridge-script-sha256", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    common = dict(
        package_path=args.package,
        base_runtime_dir=args.base_runtime_dir,
        iris_candidate_dir=args.iris_candidate_dir,
        source_eye_appearance_dir=args.source_eye_appearance_dir,
        reviewed_runtime_dir=args.reviewed_runtime_dir,
        staging_dir=args.staging_dir,
    )
    try:
        if args.command == "prepare":
            value = prepare_rebuild(args.preview_job_id, bodyrig_revision=args.bodyrig_revision, **common)
        elif args.command == "finalize":
            value = finalize_rebuild(
                args.preview_job_id,
                bodyrig_revision=args.bodyrig_revision,
                bridge_script_sha256=args.bridge_script_sha256,
                **common,
            )
        else:
            value = read_rebuild(
                args.preview_job_id,
                bridge_script_sha256=args.bridge_script_sha256,
                **common,
            )
    except (OSError, HighFidelityEyeRuntimeRebuildError) as exc:
        print(f"BodyRig eye-only runtime rebuild: FAIL: {exc}", file=sys.stderr)
        return 1

    if args.command == "prepare":
        payload = {
            "ok": True,
            "mode": "prepare",
            "bodyrig_revision": value["bodyrigRevision"],
            "base_avatar_path": value["baseAvatarPath"],
            "preparation_path": value["preparationPath"],
            "candidate_package_sha256": value["candidatePackageSha256"],
            "base_avatar_vrm_sha256": value["baseAvatarVrmSha256"],
            "source_fingerprint_sha256": value["sourceFingerprintSha256"],
            "production_activation": value["productionActivation"],
        }
    else:
        payload = {
            "ok": True,
            "mode": args.command,
            "bodyrig_revision": value["bodyrigRevision"],
            "rebuild_receipt_path": value["rebuildReceiptPath"],
            "rebuilt_vrm_path": value["rebuiltVrmPath"],
            "candidate_package_sha256": value["candidatePackageSha256"],
            "source_fingerprint_sha256": value["sourceFingerprintSha256"],
            "rebuilt_fingerprint_sha256": value["rebuiltFingerprintSha256"],
            "fingerprint_match": value["fingerprintMatch"],
            "source_hair_runtime_imported": value["sourceHairRuntimeImported"],
            "eye_only_runtime_verified": value["eyeOnlyRuntimeVerified"],
            "eye_component_authority": value["eyeComponentAuthority"],
            "package_mutation_performed": value["packageMutationPerformed"],
            "eyes_promoted": value["eyesPromoted"],
            "production_activation": value["productionActivation"],
        }
    print(json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
