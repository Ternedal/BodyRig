from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_face_secondary_runtime import (
    HighFidelityFaceSecondaryRuntimeError,
    build_runtime,
    read_runtime,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build/verify a non-activating high-fidelity face-secondary review runtime.")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--package", required=True)
    build.add_argument("--output-dir", required=True)
    build.add_argument("--bodyrig-revision", required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            value = build_runtime(args.package, args.output_dir, bodyrig_revision=args.bodyrig_revision)
        else:
            value = read_runtime(args.output_dir)
    except (OSError, HighFidelityFaceSecondaryRuntimeError) as exc:
        print(f"BodyRig face-secondary review runtime: FAIL: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "ok": True,
                "mode": args.command,
                "review_vrm_path": value["reviewVrmPath"],
                "receipt_path": value["receiptPath"],
                "review_vrm_sha256": value["reviewVrmSha256"],
                "source_package_sha256": value["sourcePackageSha256"],
                "candidate_components": value["candidateComponents"],
                "semantic_anchor_authority": value["semanticAnchorAuthority"],
                "generic_secondary_anatomy": value["genericSecondaryAnatomy"],
                "face_secondary_component_authority": value["faceSecondaryComponentAuthority"],
                "package_mutation_performed": value["packageMutationPerformed"],
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
