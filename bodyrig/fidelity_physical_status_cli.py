from __future__ import annotations

import argparse
import json
import sys

from .fidelity_physical_status import FidelityPhysicalStatusError, physical_status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only status for the frozen BodyRig #40 -> #41 physical fidelity A/B session.")
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--baseline-snapshots", required=True)
    parser.add_argument("--rig-setup", required=True)
    args = parser.parse_args(argv)
    try:
        value = physical_status(
            work_root=args.work_root,
            baseline_snapshots=args.baseline_snapshots,
            rig_setup=args.rig_setup,
        )
    except (FidelityPhysicalStatusError, OSError, ValueError) as exc:
        print(f"BodyRig fidelity physical status: BLOCKED: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
