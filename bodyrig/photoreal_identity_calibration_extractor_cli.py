from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_identity_calibration_extractor_runner import (
    PhotorealIdentityCalibrationExtractorError,
    run_external_calibration_extractor_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extract same-model non-target identity embeddings for BodyRig Photoreal V2 calibration."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--model-set", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_external_calibration_extractor_files(
            args.config,
            args.plan,
            args.model_set,
            args.workspace,
        )
    except PhotorealIdentityCalibrationExtractorError as exc:
        print(f"BodyRig photoreal identity calibration extractor: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "target_performer_id": result["target_performer_id"],
                "identity_bank_sha256": result["identity_bank_sha256"],
                "extractor": result["extractor"],
                "extractor_revision": result["extractor_revision"],
                "model_set_sha256": result["model_set_sha256"],
                "embedding_dimension": result["embedding_dimension"],
                "observation_count": len(result["observations"]),
                "calibration_only": result["calibration_only"],
                "production_activation": result["production_activation"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
