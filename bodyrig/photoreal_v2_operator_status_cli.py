from __future__ import annotations

import argparse
import json
import sys

from .photoreal_v2_operator_status import (
    PhotorealV2OperatorStatusError,
    inspect_photoreal_v2_status,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read-only BodyRig Photoreal V2 P0-to-P3 status and exact next gate. "
            "The router never records human or physical PASS."
        )
    )
    parser.add_argument("--p0-root", required=True)
    parser.add_argument("--teacher-work-root", default=None)
    parser.add_argument("--operator-root", default=None)
    parser.add_argument("--appearance-review-root", default=None)
    parser.add_argument("--asset-root", default=None)
    parser.add_argument("--reference-model-root", default=None)
    parser.add_argument("--smplx-gender", choices=("female", "male", "neutral"), default=None)
    parser.add_argument("--camera-mode", choices=("colmap", "virtual"), default=None)
    parser.add_argument("--p2-motion-config", default=None)
    parser.add_argument("--p2-review-selection-input", default=None)
    parser.add_argument("--single-motion-driver-source-ref", default=None)
    parser.add_argument("--reviewed-by", default=None)
    parser.add_argument("--review-notes", default=None)
    parser.add_argument("--p3-target-profile", default=None)
    parser.add_argument("--p3-machine-probe", default=None)
    parser.add_argument("--person-library", default=None)
    parser.add_argument("--person-id", default=None)
    parser.add_argument("--assembly-receipt", default=None)
    parser.add_argument("--body-release-status", default=None)
    parser.add_argument("--photoreal-person-binding-output", default=None)
    args = parser.parse_args(argv)

    try:
        result = inspect_photoreal_v2_status(
            p0_root=args.p0_root,
            teacher_work_root=args.teacher_work_root,
            operator_root=args.operator_root,
            appearance_review_root=args.appearance_review_root,
            asset_root=args.asset_root,
            reference_model_root=args.reference_model_root,
            smplx_gender=args.smplx_gender,
            camera_mode=args.camera_mode,
            p2_motion_config=args.p2_motion_config,
            p2_review_selection_input=args.p2_review_selection_input,
            single_motion_driver_source_ref=args.single_motion_driver_source_ref,
            reviewed_by=args.reviewed_by,
            review_notes=args.review_notes,
            p3_target_profile=args.p3_target_profile,
            p3_machine_probe=args.p3_machine_probe,
            person_library=args.person_library,
            person_id=args.person_id,
            assembly_receipt=args.assembly_receipt,
            body_release_status=args.body_release_status,
            photoreal_person_binding_output=args.photoreal_person_binding_output,
        )
    except (PhotorealV2OperatorStatusError, OSError, ValueError) as exc:
        print(f"BodyRig Photoreal V2 operator status: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            result,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 3 if result.get("state") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
