from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .photoreal_identity_calibration_diagnostic import (
    PhotorealIdentityCalibrationDiagnosticError,
    build_identity_calibration_diagnostic_files,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Explain BodyRig Photoreal Stage-13 identity calibration "
            "separation without granting authority."
        )
    )
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--identity-bank", type=Path)
    parser.add_argument("--plan", type=Path)
    parser.add_argument(
        "--negative-observations",
        type=Path,
    )
    parser.add_argument("--out", type=Path)
    parser.add_argument("--top-matches", type=int, default=10)
    return parser


def _resolve_paths(
    args: argparse.Namespace,
    parser: argparse.ArgumentParser,
) -> tuple[Path, Path, Path, Path]:
    if args.run_root is not None:
        if any(
            value is not None
            for value in (
                args.identity_bank,
                args.plan,
                args.negative_observations,
            )
        ):
            parser.error(
                "--run-root cannot be combined with explicit "
                "identity-bank/plan/negative-observations paths"
            )

        root = args.run_root.expanduser().resolve()
        output = (
            args.out
            if args.out is not None
            else root / "identity-calibration-diagnostic.json"
        )
        return (
            root / "identity-bank.json",
            root / "identity-calibration-plan.json",
            root
            / "identity-calibration-extractor"
            / "output"
            / "negative-observations.json",
            output,
        )

    missing = [
        option
        for option, value in (
            ("--identity-bank", args.identity_bank),
            ("--plan", args.plan),
            (
                "--negative-observations",
                args.negative_observations,
            ),
            ("--out", args.out),
        )
        if value is None
    ]
    if missing:
        parser.error(
            "explicit diagnostic mode requires "
            + ", ".join(missing)
        )

    return (
        args.identity_bank,
        args.plan,
        args.negative_observations,
        args.out,
    )


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    (
        identity_bank_path,
        plan_path,
        negative_observations_path,
        output_path,
    ) = _resolve_paths(args, parser)

    try:
        result = build_identity_calibration_diagnostic_files(
            identity_bank_path,
            plan_path,
            negative_observations_path,
            output_path,
            top_matches=args.top_matches,
        )
    except PhotorealIdentityCalibrationDiagnosticError as exc:
        print(
            "BodyRig photoreal identity calibration diagnostic: "
            f"FAIL: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "target_performer_id":
                    result["target_performer_id"],
                "positive_floor":
                    result["positive_floor"],
                "negative_ceiling":
                    result["negative_ceiling"],
                "observed_separation_margin":
                    result["observed_separation_margin"],
                "minimum_required_separation_margin":
                    result["minimum_required_separation_margin"],
                "maximum_allowed_negative_cosine":
                    result["maximum_allowed_negative_cosine"],
                "stage13_calibration_blockers":
                    result["stage13_calibration_blockers"],
                "violating_negative_observation_count":
                    result[
                        "violating_negative_observation_count"
                    ],
                "violating_negative_observation_fraction":
                    result[
                        "violating_negative_observation_fraction"
                    ],
                "violating_negative_performer_count":
                    result[
                        "violating_negative_performer_count"
                    ],
                "violating_negative_source_count":
                    result[
                        "violating_negative_source_count"
                    ],
                "violating_closest_positive_group_summaries":
                    result[
                        "violating_closest_positive_group_summaries"
                    ],
                "positive_cosine_median":
                    result["positive_cosine_median"],
                "positive_reference_to_target_cosine_min":
                    result[
                        "positive_reference_to_target_cosine_min"
                    ],
                "positive_cross_group_centroid_cosine_min":
                    result[
                        "positive_cross_group_centroid_cosine_min"
                    ],
                "positive_group_count":
                    result["positive_group_count"],
                "weakest_positive_group":
                    result["weakest_positive_group"],
                "negative_cosine_median":
                    result["negative_cosine_median"],
                "planned_negative_observation_count":
                    result["planned_negative_observation_count"],
                "negative_observation_count":
                    result["negative_observation_count"],
                "negative_observation_quality_metadata":
                    result[
                        "negative_observation_quality_metadata"
                    ],
                "negative_extraction_yield_fraction":
                    result["negative_extraction_yield_fraction"],
                "planned_negative_source_count":
                    result["planned_negative_source_count"],
                "observed_negative_source_count":
                    result["observed_negative_source_count"],
                "lowest_yield_negative_performer":
                    result["lowest_yield_negative_performer"],
                "lowest_yield_negative_source":
                    result["lowest_yield_negative_source"],
                "highest_collision_negative_performer":
                    result["highest_collision_negative_performer"],
                "highest_collision_negative_source":
                    result["highest_collision_negative_source"],
                "highest_negative_match":
                    result["highest_negative_match"],
                "diagnostic_only":
                    result["diagnostic_only"],
                "identity_matching_authority":
                    result["identity_matching_authority"],
                "production_activation":
                    result["production_activation"],
                "output":
                    str(output_path.expanduser().resolve()),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
