from __future__ import annotations

import argparse
import json
from dataclasses import asdict, replace
from pathlib import Path

from .acceptance_status import (
    AcceptanceStatus,
    AcceptanceStatusError,
    _session_status,
    inspect_acceptance_dir,
)


def _quote(path: str) -> str:
    return f'"{path}"'


def _operator_command(status: AcceptanceStatus) -> AcceptanceStatus:
    if not status.acceptance_dir:
        return status
    if status.gate == "windows-attestation":
        return replace(
            status,
            next_command=(
                ".\\record-reference-renderer-acceptance.ps1 "
                f"-AcceptanceDir {_quote(status.acceptance_dir)} "
                '-Platform "windows-unity-univrm" '
                '-QualityNote "<your physical review>"'
            ),
        )
    if status.gate == "quest-attestation":
        return replace(
            status,
            next_command=(
                ".\\record-reference-renderer-acceptance.ps1 "
                f"-AcceptanceDir {_quote(status.acceptance_dir)} "
                '-Platform "android-quest-class" '
                '-QualityNote "<your physical headset review>"'
            ),
        )
    return status


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only BodyRig physical acceptance status checker")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--session-report", type=Path, help="bodyrig-physical-clone-session JSON")
    inputs.add_argument("--acceptance-dir", type=Path, help="Gate A acceptance directory")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable status JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        status = _session_status(args.session_report) if args.session_report else inspect_acceptance_dir(args.acceptance_dir)
        status = _operator_command(status)
    except AcceptanceStatusError as exc:
        if args.json:
            print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"BodyRig acceptance status: ERROR | {exc}")
        return 2

    if args.json:
        print(json.dumps(asdict(status), ensure_ascii=False, sort_keys=True))
    else:
        print(f"BodyRig acceptance status: {status.state.upper()} | {status.gate}")
        print(status.message)
        if status.body_id:
            print(f"Body: {status.body_id}")
        if status.bodyrig_revision:
            print(f"Revision: {status.bodyrig_revision}")
        if status.acceptance_dir:
            print(f"Acceptance: {status.acceptance_dir}")
        if status.next_command:
            print("Next command:")
            print(status.next_command)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
