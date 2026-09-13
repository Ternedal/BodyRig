from __future__ import annotations

import argparse
import json
import sys

from .high_fidelity_hfn_migration import HighFidelityHfnMigrationError, prepare_migration


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create an explicit current-integration HFN authority for a legacy-complete high-fidelity preview"
    )
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--integration-bodyrig-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = prepare_migration(
            args.preview_job_id,
            integration_bodyrig_revision=args.integration_bodyrig_revision,
        )
    except (OSError, ValueError, HighFidelityHfnMigrationError) as exc:
        print(f"BodyRig HFN migration: ERROR | {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
