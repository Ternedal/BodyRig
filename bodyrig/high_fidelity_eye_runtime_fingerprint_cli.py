from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_eye_runtime_fingerprint import (
    HighFidelityEyeRuntimeFingerprintError,
    write_fingerprint,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record a canonical semantic fingerprint for the exact reviewed source-eye runtime."
    )
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--base-runtime-dir", required=True)
    parser.add_argument("--iris-candidate-dir", required=True)
    parser.add_argument("--source-eye-appearance-dir", required=True)
    parser.add_argument("--reviewed-runtime-dir", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    args = parser.parse_args(argv)
    try:
        result = write_fingerprint(
            args.preview_job_id,
            base_runtime_dir=args.base_runtime_dir,
            iris_candidate_dir=args.iris_candidate_dir,
            source_eye_appearance_dir=args.source_eye_appearance_dir,
            reviewed_runtime_dir=args.reviewed_runtime_dir,
            bodyrig_revision=args.bodyrig_revision,
        )
    except (OSError, HighFidelityEyeRuntimeFingerprintError) as exc:
        print(f"BodyRig eye runtime fingerprint: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, separators=(",", ":"), sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
