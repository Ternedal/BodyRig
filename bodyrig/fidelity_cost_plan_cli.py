from __future__ import annotations

import argparse
import json
import sys

from .fidelity_cost_plan import FidelityCostPlanError, FidelityCostPolicy, next_action


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan the next cost-aware BodyRig fidelity action.")
    parser.add_argument("--state", required=True, choices=("iterate", "plateau", "converged", "manual-review"))
    parser.add_argument("--full-rebuilds-completed", required=True, type=int)
    parser.add_argument("--refinements-on-current-rebuild", required=True, type=int)
    parser.add_argument("--adjustment-request-sha256", default="")
    parser.add_argument("--used-adjustment-sha256", action="append", default=[])
    parser.add_argument("--max-full-rebuilds", type=int, default=2)
    parser.add_argument("--max-refinements-per-rebuild", type=int, default=3)
    args = parser.parse_args(argv)

    try:
        policy = FidelityCostPolicy(
            max_full_rebuilds=args.max_full_rebuilds,
            max_refinements_per_rebuild=args.max_refinements_per_rebuild,
        )
        result = next_action(
            convergence_state=args.state,
            full_rebuilds_completed=args.full_rebuilds_completed,
            refinements_on_current_rebuild=args.refinements_on_current_rebuild,
            adjustment_request_sha256=args.adjustment_request_sha256 or None,
            used_adjustment_sha256=args.used_adjustment_sha256,
            policy=policy,
        )
    except FidelityCostPlanError as exc:
        print(f"BodyRig fidelity cost plan: FAIL: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
