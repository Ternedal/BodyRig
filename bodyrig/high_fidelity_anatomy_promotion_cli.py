from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_anatomy_promotion import (
    HighFidelityAnatomyPromotionError,
    read_promotion,
    write_promotion,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Materialize a reviewed BodyRig anatomy candidate into a new anatomy-promoted .mrbody package."
    )
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)
    created_package = ""
    created_receipt = ""
    try:
        result = write_promotion(
            args.preview_job_id,
            bodyrig_revision=args.bodyrig_revision,
        )
        created_package = str(result["package_path"])
        created_receipt = str(result["receipt_path"])
        verified = read_promotion(args.preview_job_id)
    except (OSError, HighFidelityAnatomyPromotionError) as exc:
        print(f"BodyRig high-fidelity anatomy promotion: FAIL: {exc}", file=sys.stderr)
        return 1
    payload = {
        "ok": True,
        "preview_job_id": verified["preview_job_id"],
        "canonical_body_id": verified["canonical_body_id"],
        "bodyrig_revision": verified["bodyrig_revision"],
        "source_package_sha256": verified["source_package_sha256"],
        "component_review_sha256": verified["component_review_sha256"],
        "promoted_package_sha256": verified["promoted_package_sha256"],
        "promoted_avatar_sha256": verified["promoted_avatar_sha256"],
        "components_after": verified["components_after"],
        "promotion_component": verified["promotion_component"],
        "production_activation": verified["production_activation"],
        "package_path": created_package,
        "receipt_path": created_receipt,
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
