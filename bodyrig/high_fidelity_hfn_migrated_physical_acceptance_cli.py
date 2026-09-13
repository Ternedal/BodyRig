from __future__ import annotations

import argparse
import json
import sys

from . import high_fidelity_physical_acceptance as physical
from .high_fidelity_hfn_migrated_status import inspect_migrated_continuation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create fresh Gate A from an HFN-migrated high-fidelity preview")
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--bodyrig-revision", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    original = physical.inspect_continuation
    physical.inspect_continuation = inspect_migrated_continuation
    try:
        result = physical.prepare_physical_acceptance(
            args.preview_job_id,
            bodyrig_revision=args.bodyrig_revision,
        )
    except (OSError, ValueError, physical.HighFidelityPhysicalAcceptanceError) as exc:
        print(f"BodyRig migrated high-fidelity physical handoff: ERROR | {exc}", file=sys.stderr)
        return 2
    finally:
        physical.inspect_continuation = original
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
