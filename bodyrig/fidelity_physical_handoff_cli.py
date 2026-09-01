from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .fidelity_physical_handoff import (
    FidelityPhysicalHandoffError,
    seal_physical_handoff,
    verify_physical_handoff,
)


def _policy(text: str) -> dict:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FidelityPhysicalHandoffError("--policy-json is invalid JSON") from exc
    if not isinstance(value, dict):
        raise FidelityPhysicalHandoffError("--policy-json must be an object")
    return value


def _read_receipt(path: Path) -> dict:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8-sig"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise FidelityPhysicalHandoffError(f"physical handoff receipt is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise FidelityPhysicalHandoffError("physical handoff receipt must be a JSON object")
    return value


def _write_create_only(path: Path, value: dict) -> None:
    resolved = path.expanduser().resolve()
    if resolved.exists():
        raise FidelityPhysicalHandoffError(f"physical handoff receipt already exists: {resolved}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
    try:
        with resolved.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(raw)
    except OSError as exc:
        raise FidelityPhysicalHandoffError(f"could not create physical handoff receipt: {resolved}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Seal or verify the human-approved #40 physical-fidelity handoff before a #41 appearance-only A/B fit."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    seal = sub.add_parser("seal")
    seal.add_argument("--work-root", required=True)
    seal.add_argument("--rig-setup", required=True)
    seal.add_argument("--revision", required=True)
    seal.add_argument("--performer-id", required=True)
    seal.add_argument("--body-alias", required=True)
    seal.add_argument("--policy-json", required=True)
    seal.add_argument("--human-geometry-approved", action="store_true")
    seal.add_argument("--out", required=True)

    verify = sub.add_parser("verify")
    verify.add_argument("--work-root", required=True)
    verify.add_argument("--rig-setup", required=True)
    verify.add_argument("--revision", required=True)
    verify.add_argument("--performer-id", required=True)
    verify.add_argument("--body-alias", required=True)
    verify.add_argument("--receipt", required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "seal":
            value = seal_physical_handoff(
                work_root=args.work_root,
                rig_setup=args.rig_setup,
                expected_revision=args.revision,
                expected_performer_id=args.performer_id,
                expected_body_alias=args.body_alias,
                expected_policy=_policy(args.policy_json),
                human_geometry_approved=bool(args.human_geometry_approved),
            )
            output = Path(args.out).expanduser().resolve()
            _write_create_only(output, value)
            print(json.dumps({"ok": True, "receipt": str(output), "handoff": value}, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
        else:
            receipt_path = Path(args.receipt).expanduser().resolve()
            value = verify_physical_handoff(
                _read_receipt(receipt_path),
                work_root=args.work_root,
                rig_setup=args.rig_setup,
                expected_revision=args.revision,
                expected_performer_id=args.performer_id,
                expected_body_alias=args.body_alias,
            )
            print(json.dumps({"ok": True, "receipt": str(receipt_path), "handoff": value}, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    except (FidelityPhysicalHandoffError, OSError, ValueError) as exc:
        print(f"BodyRig physical handoff: FAIL: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
