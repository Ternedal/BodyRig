from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_hair_promotion import (
    HighFidelityHairPromotionError,
    prepare_promotion_inputs,
    read_promotion,
    write_promotion,
)


def _emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare or materialize exact hash-bound BodyRig high-fidelity hair promotion."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("--preview-job-id", required=True)

    promote = sub.add_parser("promote")
    promote.add_argument("--preview-job-id", required=True)
    promote.add_argument("--promotion-bodyrig-revision", required=True)
    promote.add_argument("--hair-runtime-dir", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            value = prepare_promotion_inputs(args.preview_job_id)
            _emit({"ok": True, **value})
            return 0

        result = write_promotion(
            args.preview_job_id,
            promotion_bodyrig_revision=args.promotion_bodyrig_revision,
            hair_runtime_dir=args.hair_runtime_dir,
        )
        verified = read_promotion(args.preview_job_id)
        if result["promoted_package_sha256"] != verified["promoted_package_sha256"]:
            raise HighFidelityHairPromotionError("post-write hair promotion verification changed package identity")
        _emit(
            {
                "ok": True,
                "preview_job_id": verified["preview_job_id"],
                "canonical_body_id": verified["canonical_body_id"],
                "source_bodyrig_revision": verified["source_bodyrig_revision"],
                "promotion_bodyrig_revision": verified["promotion_bodyrig_revision"],
                "source_candidate_package_sha256": verified["source_candidate_package_sha256"],
                "anatomy_promoted_package_sha256": verified["anatomy_promoted_package_sha256"],
                "hair_deformation_review_sha256": verified["hair_deformation_review_sha256"],
                "expected_hair_review_bridge_sha256": verified["expected_hair_review_bridge_sha256"],
                "rebuilt_hair_bridge_canonical_sha256": verified["rebuilt_hair_bridge_canonical_sha256"],
                "promoted_package_sha256": verified["promoted_package_sha256"],
                "promoted_avatar_sha256": verified["promoted_avatar_sha256"],
                "components_after": verified["components_after"],
                "promotion_component": verified["promotion_component"],
                "eyes_imported": False,
                "production_activation": verified["production_activation"],
                "promotion_root": verified["promotion_root"],
                "package_path": verified["package_path"],
                "receipt_path": verified["receipt_path"],
            }
        )
        return 0
    except (OSError, HighFidelityHairPromotionError) as exc:
        print(f"BodyRig high-fidelity hair promotion: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
