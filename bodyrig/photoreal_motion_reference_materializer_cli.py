from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_motion_reference_materialization_authority import (
    PhotorealMotionReferenceAuthorityError,
    validate_motion_materialization_authority,
    write_motion_materialization_receipt,
)
from .photoreal_motion_reference_materializer import (
    ADAPTER,
    PhotorealMotionReferenceMaterializerError,
    build_motion_materialization_request,
    run_external_motion_materializer,
)


def _read_json(path: str, *, label: str) -> dict[str, object]:
    source = Path(path).expanduser().resolve()
    try:
        value = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PhotorealMotionReferenceMaterializerError(f"{label} is unreadable: {source}") from exc
    if not isinstance(value, dict):
        raise PhotorealMotionReferenceMaterializerError(f"{label} must be a JSON object")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize exact held-out Photoreal P2 motion-review windows behind strict BodyRig authority."
    )
    parser.add_argument("--config", required=True)
    parser.add_argument("--animated-review-plan", required=True)
    parser.add_argument("--workspace", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    workspace = Path(args.workspace).expanduser().resolve()
    try:
        config = _read_json(args.config, label="motion materializer config")
        plan = _read_json(args.animated_review_plan, label="animated review plan")
        result = run_external_motion_materializer(config, plan, workspace=workspace)
        revision = config.get("revision")
        if not isinstance(revision, str):
            raise PhotorealMotionReferenceMaterializerError("motion materializer config revision is invalid")
        request = build_motion_materialization_request(plan, adapter=ADAPTER, revision=revision)
        strict = validate_motion_materialization_authority(
            result,
            request=request,
            output_dir=workspace / "output",
        )
        receipt = write_motion_materialization_receipt(
            strict,
            workspace / "motion-materialization-receipt.json",
        )
    except (PhotorealMotionReferenceMaterializerError, PhotorealMotionReferenceAuthorityError) as exc:
        print(f"BodyRig Photoreal motion materializer: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "format": receipt["format"],
        "version": receipt["version"],
        "performer_id": receipt["performer_id"],
        "window_count": receipt["window_count"],
        "sample_fps": receipt["sample_fps"],
        "all_source_hashes_verified": receipt["all_source_hashes_verified"],
        "all_anchor_hashes_verified": receipt["all_anchor_hashes_verified"],
        "artifact_bytes_verified_by_core": receipt["artifact_bytes_verified_by_core"],
        "reference_motion_bytes_materialized": receipt["reference_motion_bytes_materialized"],
        "animated_teacher_acceptance_authority": receipt["animated_teacher_acceptance_authority"],
        "p3_device_distillation_authorized": receipt["p3_device_distillation_authorized"],
        "production_activation": receipt["production_activation"],
        "motion_materialization_receipt_sha256": receipt["motion_materialization_receipt_sha256"],
    }, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
