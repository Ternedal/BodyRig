from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .digital_twin_platform_acceptance import (
    DigitalTwinPlatformAcceptanceError,
    _expected_input_files,
    build_platform_input,
    inspect_digital_twin_platform_acceptance,
    validate_realization_receipt,
    write_platform_input,
)


def _emit(value: dict) -> None:
    print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))


def _prepare(args: argparse.Namespace) -> dict:
    return write_platform_input(
        args.output_dir,
        composition_authority_dir=args.composition_authority_dir,
        acceptance_dir=args.acceptance_dir,
        platform=args.platform,
    )


def _validate(args: argparse.Namespace) -> dict:
    evidence = Path(args.evidence_dir).expanduser().resolve()
    expected, motor_raw = build_platform_input(
        composition_authority_dir=args.composition_authority_dir,
        acceptance_dir=args.acceptance_dir,
        platform=args.platform,
    )
    manifest_path, motor_path = _expected_input_files(evidence, expected=expected, motor_raw=motor_raw)
    receipt = validate_realization_receipt(
        evidence / "realization.json",
        expected_input=expected,
        input_manifest_path=manifest_path,
    )
    return {
        "ok": True,
        "platform": args.platform,
        "evidence_dir": str(evidence),
        "input_manifest": str(manifest_path),
        "motor_state": str(motor_path),
        "realization": str(evidence / "realization.json"),
        "build_guid": receipt["build_guid"],
        "device_model": receipt["device_model"],
        "production_activation": False,
    }


def _status(args: argparse.Namespace) -> dict:
    return inspect_digital_twin_platform_acceptance(
        composition_authority_dir=args.composition_authority_dir,
        acceptance_dir=args.acceptance_dir,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BodyRig M5 digital-twin platform acceptance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare", help="Create exact non-activating platform input")
    prepare.add_argument("--composition-authority-dir", required=True)
    prepare.add_argument("--acceptance-dir", required=True)
    prepare.add_argument("--platform", required=True, choices=("windows-unity-univrm", "android-quest-class"))
    prepare.add_argument("--output-dir", required=True)
    prepare.set_defaults(handler=_prepare)

    validate = subparsers.add_parser("validate", help="Validate one physically produced M5 realization")
    validate.add_argument("--composition-authority-dir", required=True)
    validate.add_argument("--acceptance-dir", required=True)
    validate.add_argument("--platform", required=True, choices=("windows-unity-univrm", "android-quest-class"))
    validate.add_argument("--evidence-dir", required=True)
    validate.set_defaults(handler=_validate)

    status = subparsers.add_parser("status", help="Inspect both M5 platform gates")
    status.add_argument("--composition-authority-dir", required=True)
    status.add_argument("--acceptance-dir", required=True)
    status.set_defaults(handler=_status)

    args = parser.parse_args(argv)
    try:
        result = args.handler(args)
    except (DigitalTwinPlatformAcceptanceError, OSError, ValueError) as exc:
        print(f"BodyRig M5 digital-twin platform acceptance: FAIL: {exc}", file=sys.stderr)
        return 1
    _emit(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
