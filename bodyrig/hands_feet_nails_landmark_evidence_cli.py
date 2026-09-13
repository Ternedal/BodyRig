from __future__ import annotations

import argparse
import json
import sys

from .hands_feet_nails_landmark_evidence import (
    HandsFeetNailsLandmarkEvidenceError,
    build_landmark_evidence,
)
from .photoidentity_openpose_runner import PhotoIdentityOpenPoseRunnerError
from .storage import person_library


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build Person/body-bound hands/feet/nails semantic landmark evidence from an exact M2 source capture. "
            "This evidence is source-coordinate-only and never grants package or production authority."
        )
    )
    parser.add_argument("--person-id", required=True)
    parser.add_argument("--body-revision", required=True)
    parser.add_argument("--capture-id", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    parser.add_argument("--ffmpeg-exe", default="ffmpeg")
    parser.add_argument("--distribution", required=True)
    parser.add_argument("--openpose", required=True)
    parser.add_argument("--wsl-exe", default="wsl.exe")
    args = parser.parse_args(argv)

    try:
        result = build_landmark_evidence(
            person_library(),
            args.person_id,
            body_revision=args.body_revision,
            capture_id=args.capture_id,
            evidence_bodyrig_revision=args.bodyrig_revision,
            ffmpeg=args.ffmpeg_exe,
            distribution=args.distribution,
            openpose=args.openpose,
            wsl_exe=args.wsl_exe,
        )
    except (
        OSError,
        ValueError,
        HandsFeetNailsLandmarkEvidenceError,
        PhotoIdentityOpenPoseRunnerError,
    ) as exc:
        print(f"BodyRig HFN landmark evidence: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "ok": True,
                "person_id": result["person_id"],
                "body_revision": result["body_revision"],
                "capture_id": result["capture_id"],
                "source_bodyrig_revision": result["source_bodyrig_revision"],
                "evidence_bodyrig_revision": result["evidence_bodyrig_revision"],
                "source_capture_sha256": result["source_capture_sha256"],
                "all_regions_application_ready": result["all_regions_application_ready"],
                "manifest": result["manifest"],
                "package_application_authority": False,
                "production_activation": False,
            },
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
