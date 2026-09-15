from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_identity_extractor_runner import (
    PhotorealIdentityExtractorError,
    run_external_identity_extractor_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a strict external identity embedding extractor for BodyRig Photoreal V2."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--bootstrap", type=Path, required=True)
    parser.add_argument("--model-set", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = run_external_identity_extractor_files(
            args.config,
            args.bootstrap,
            args.model_set,
            args.workspace,
        )
    except PhotorealIdentityExtractorError as exc:
        print(f"BodyRig photoreal identity extractor: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "extractor": result["extractor"],
                "extractor_revision": result["extractor_revision"],
                "model_set_sha256": result["model_set_sha256"],
                "embedding_dimension": result["embedding_dimension"],
                "observation_count": len(result["observations"]),
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
