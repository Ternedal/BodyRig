from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from . import high_fidelity_release_readiness as readiness
from . import high_fidelity_release_readiness_cli as canonical_cli
from .high_fidelity_hfn_migrated_status import (
    HighFidelityHfnMigratedStatusError,
    inspect_migrated_continuation,
)

GIT_RE = re.compile(r"^[0-9a-f]{40}$")


class HighFidelityHfnMigratedReadinessError(RuntimeError):
    pass


def inspect_migrated_release_readiness(preview_job_id: str) -> dict[str, Any]:
    original = readiness.inspect_continuation
    readiness.inspect_continuation = inspect_migrated_continuation
    try:
        return readiness.inspect_release_readiness(preview_job_id)
    finally:
        readiness.inspect_continuation = original


def _rewrite_migrated_gate_a(result: dict[str, Any]) -> dict[str, Any]:
    next_gate = result.get("next_gate")
    if not isinstance(next_gate, dict):
        return result
    command = str(next_gate.get("command") or "")
    if "prepare-high-fidelity-physical-acceptance.ps1" not in command:
        return result
    value = dict(result)
    next_value = dict(next_gate)
    next_value["command"] = command.replace(
        "prepare-high-fidelity-physical-acceptance.ps1",
        "prepare-high-fidelity-migrated-physical-acceptance.ps1",
    )
    value["next_gate"] = next_value
    return value


def _bind(result: dict[str, Any], root: Path, *, quest_serial: str | None) -> dict[str, Any]:
    bound = canonical_cli.bind_operator_checkout(result, root, quest_serial=quest_serial)
    if bound.get("hfn_migration_active") is not True:
        return _rewrite_migrated_gate_a(bound)
    expected = str(bound.get("hfn_bodyrig_revision") or "").strip().lower()
    checkout = bound.get("operator_checkout")
    actual = str(checkout.get("revision") or "").strip().lower() if isinstance(checkout, dict) else ""
    if not GIT_RE.fullmatch(expected) or actual != expected:
        value = dict(bound)
        value["state"] = "blocked"
        value["next_gate"] = None
        value["production_ready"] = False
        value["production_activation"] = False
        value["operator_checkout"] = {
            **(dict(checkout) if isinstance(checkout, dict) else {}),
            "authorized": False,
            "reason": (
                "HFN migration is frozen to integration revision "
                f"{expected or 'unknown'}, but operator checkout is {actual or 'unknown'}."
            ),
        }
        return value
    return _rewrite_migrated_gate_a(bound)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migration-aware high-fidelity release/readiness status")
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--operator-root", type=Path)
    parser.add_argument("--quest-serial")
    parser.add_argument("--json", action="store_true")
    return parser


def _print(result: dict[str, Any]) -> None:
    print(f"BodyRig migrated high-fidelity readiness: {str(result.get('state') or 'unknown').upper()}")
    if result.get("legacy_bodyrig_revision"):
        print(f"Legacy revision: {result['legacy_bodyrig_revision']}")
    if result.get("hfn_bodyrig_revision"):
        print(f"HFN revision:    {result['hfn_bodyrig_revision']}")
    if result.get("current_package_sha256"):
        print(f"Package SHA:     {result['current_package_sha256']}")
    checkout = result.get("operator_checkout")
    if isinstance(checkout, dict):
        print(
            f"Checkout:        {checkout.get('revision') or 'unknown'} | "
            f"clean={bool(checkout.get('clean'))} | authorized={bool(checkout.get('authorized'))}"
        )
        if checkout.get("authorized") is False and checkout.get("reason"):
            print(f"Checkout block:  {checkout['reason']}")
    next_gate = result.get("next_gate")
    if isinstance(next_gate, dict):
        print(f"Next gate:       {next_gate.get('gate') or 'unknown'}")
        reason = str(next_gate.get("reason") or "").strip()
        if reason:
            print(reason)
        command = str(next_gate.get("command") or "").strip()
        if command:
            print("Next command:")
            print(command)
    elif result.get("production_ready") is True and result.get("production_activation") is True:
        print("PRODUCTION READY: canonical final release PASS is active for this exact migrated evidence chain.")
    elif result.get("state") == "blocked":
        blockers = [
            str(gate.get("reason") or "").strip()
            for gate in result.get("gates") or []
            if isinstance(gate, dict) and gate.get("state") in {"blocked", "invalid"}
        ]
        if blockers:
            print(f"Blocked: {blockers[-1]}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = inspect_migrated_release_readiness(args.preview_job_id)
        if args.operator_root is not None:
            result = _bind(result, args.operator_root, quest_serial=args.quest_serial)
    except (
        OSError,
        ValueError,
        readiness.HighFidelityReleaseReadinessError,
        canonical_cli.HighFidelityReleaseReadinessCliError,
        HighFidelityHfnMigratedStatusError,
        HighFidelityHfnMigratedReadinessError,
    ) as exc:
        if args.json:
            print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"BodyRig migrated high-fidelity readiness: ERROR | {exc}")
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    else:
        _print(result)
    return 3 if result.get("state") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
