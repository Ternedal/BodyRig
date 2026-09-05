from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .high_fidelity_release_readiness import HighFidelityReleaseReadinessError, inspect_release_readiness

SHA40 = re.compile(r"^[0-9a-f]{40}$")


class HighFidelityReleaseReadinessCliError(RuntimeError):
    pass


def _git_state(root: Path) -> tuple[str, bool]:
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise HighFidelityReleaseReadinessCliError("Git executable is unavailable for operator checkout validation") from exc
    revision = head.stdout.strip().lower()
    if head.returncode != 0 or not SHA40.fullmatch(revision):
        raise HighFidelityReleaseReadinessCliError(f"could not resolve canonical operator checkout revision: {root}")
    if dirty.returncode != 0:
        raise HighFidelityReleaseReadinessCliError(f"could not inspect operator checkout cleanliness: {root}")
    return revision, not bool(dirty.stdout.strip())


def _accepted_revision(result: dict[str, Any]) -> str | None:
    for gate in result.get("gates") or []:
        if not isinstance(gate, dict) or gate.get("id") != "physical_gate_a" or gate.get("state") != "pass":
            continue
        evidence = gate.get("evidence")
        if not isinstance(evidence, dict):
            continue
        revision = str(evidence.get("bodyrig_revision") or "").strip().lower()
        return revision if SHA40.fullmatch(revision) else None
    return None


def _absolutize_command(command: str, root: Path) -> str:
    if not command.startswith(".\\"):
        return command
    parts = command.split(" ", 1)
    script = parts[0][2:]
    target = (root / script).resolve()
    if not target.is_file():
        raise HighFidelityReleaseReadinessCliError(f"next operator script is missing from checkout: {target}")
    suffix = "" if len(parts) == 1 else " " + parts[1]
    return f'& "{target}"{suffix}'


def _blocked_for_checkout(result: dict[str, Any], reason: str, *, root: Path, revision: str | None = None) -> dict[str, Any]:
    value = dict(result)
    value["state"] = "blocked"
    value["next_gate"] = None
    value["production_ready"] = False
    value["production_activation"] = False
    value["operator_checkout"] = {
        "root": str(root),
        "revision": revision,
        "clean": False,
        "authorized": False,
        "reason": reason,
    }
    return value


def bind_operator_checkout(result: dict[str, Any], operator_root: Path) -> dict[str, Any]:
    root = operator_root.expanduser().resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise HighFidelityReleaseReadinessCliError(f"operator root is not a BodyRig Git checkout: {root}")
    revision, clean = _git_state(root)
    if not clean:
        return _blocked_for_checkout(
            result,
            "BodyRig operator checkout is dirty; refusing to authorize the next physical command.",
            root=root,
            revision=revision,
        )

    expected = _accepted_revision(result)
    if expected is not None and revision != expected:
        return _blocked_for_checkout(
            result,
            f"operator checkout revision {revision} does not match fresh Gate A revision {expected}",
            root=root,
            revision=revision,
        )

    value = dict(result)
    next_gate = result.get("next_gate")
    if isinstance(next_gate, dict):
        next_value = dict(next_gate)
        command = str(next_value.get("command") or "").strip()
        if command:
            next_value["command"] = _absolutize_command(command, root)
        value["next_gate"] = next_value
    value["operator_checkout"] = {
        "root": str(root),
        "revision": revision,
        "clean": True,
        "authorized": True,
        "accepted_revision": expected,
    }
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only high-fidelity release/readiness status for rig operators")
    parser.add_argument("--preview-job-id", required=True)
    parser.add_argument("--operator-root", type=Path)
    parser.add_argument("--json", action="store_true")
    return parser


def _print_human(result: dict[str, Any]) -> None:
    state = str(result.get("state") or "unknown")
    print(f"BodyRig high-fidelity readiness: {state.upper()}")
    package_sha = str(result.get("current_package_sha256") or "")
    if package_sha:
        print(f"Package SHA: {package_sha}")
    acceptance = str(result.get("physical_acceptance_dir") or "")
    if acceptance:
        print(f"Acceptance: {acceptance}")
    checkout = result.get("operator_checkout")
    if isinstance(checkout, dict):
        print(f"Checkout: {checkout.get('revision') or 'unknown'} | clean={bool(checkout.get('clean'))} | authorized={bool(checkout.get('authorized'))}")
    next_gate = result.get("next_gate")
    if isinstance(next_gate, dict):
        print(f"Next gate: {next_gate.get('gate') or 'unknown'}")
        reason = str(next_gate.get("reason") or "").strip()
        if reason:
            print(reason)
        command = str(next_gate.get("command") or "").strip()
        if command:
            print("Next command:")
            print(command)
    elif result.get("production_ready") is True and result.get("production_activation") is True:
        print("PRODUCTION READY: canonical final release PASS is active for this exact package/evidence chain.")
    else:
        blockers = [
            str(gate.get("reason") or "").strip()
            for gate in result.get("gates") or []
            if isinstance(gate, dict) and gate.get("state") in {"blocked", "invalid"}
        ]
        if blockers:
            print("Blocked:")
            print(blockers[-1])


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = inspect_release_readiness(args.preview_job_id)
        if args.operator_root is not None:
            result = bind_operator_checkout(result, args.operator_root)
    except (OSError, ValueError, HighFidelityReleaseReadinessError, HighFidelityReleaseReadinessCliError) as exc:
        if args.json:
            print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False, sort_keys=True))
        else:
            print(f"BodyRig high-fidelity readiness: ERROR | {exc}")
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        _print_human(result)
    return 3 if result.get("state") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
