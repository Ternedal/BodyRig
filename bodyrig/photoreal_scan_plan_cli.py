from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .photoreal_explicit_projection_authority import (
    PhotorealExplicitProjectionAuthorityError,
    resolve_projection_authority,
)
from .photoreal_projection_authority import PhotorealProjectionAuthorityError
from .photoreal_scan_plan import PhotorealScanPlanError, build_scan_plan

PROJECTION_AUTHORITY_ENV = "BODYRIG_PHOTOREAL_PROJECTION_AUTHORITY"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a deterministic byte-bound scout scan plan for Photoreal V2."
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--projection-authority", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    return parser


def _read_json(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(
            path.expanduser().resolve().read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PhotorealScanPlanError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise PhotorealScanPlanError(f"{label} must be a JSON object")
    return value


def _projection_authority_path(argument: Path | None) -> Path | None:
    environment_value = str(os.environ.get(PROJECTION_AUTHORITY_ENV) or "").strip()
    if argument is None:
        return Path(environment_value) if environment_value else None
    if environment_value:
        argument_path = argument.expanduser().resolve()
        environment_path = Path(environment_value).expanduser().resolve()
        if argument_path != environment_path:
            raise PhotorealScanPlanError(
                f"--projection-authority conflicts with {PROJECTION_AUTHORITY_ENV}"
            )
    return argument


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        plan = _read_json(args.plan, label="photoreal dataset plan")
        receipt = _read_json(args.receipt, label="photoreal source receipt")
        explicit_path = _projection_authority_path(args.projection_authority)
        explicit_manifest = (
            _read_json(explicit_path, label="photoreal explicit projection authority")
            if explicit_path is not None
            else None
        )
        resolved_plan, resolved_v2_count, resolved_explicit_count = resolve_projection_authority(
            plan,
            receipt,
            explicit_manifest,
        )
        result = build_scan_plan(resolved_plan, receipt)
        output = args.out.expanduser().resolve()
        if output.exists():
            raise PhotorealScanPlanError(f"photoreal scan plan already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
    except (
        PhotorealExplicitProjectionAuthorityError,
        PhotorealProjectionAuthorityError,
        PhotorealScanPlanError,
    ) as exc:
        print(f"BodyRig photoreal scan plan: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "format": result["format"],
                "version": result["version"],
                "performer_id": result["performer_id"],
                "source_count": result["source_count"],
                "planned_observation_count": result["planned_observation_count"],
                "strategy": result["strategy"],
                "resolved_v2_projection_source_count": resolved_v2_count,
                "resolved_explicit_projection_source_count": resolved_explicit_count,
                "frame_analyzer_required": result["frame_analyzer_required"],
                "teacher_training_authorized": result["teacher_training_authorized"],
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
