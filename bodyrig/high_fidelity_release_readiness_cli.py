from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .acceptance_status import AcceptanceStatusError, inspect_acceptance_dir
from .acceptance_status_cli import CANONICAL_OPERATOR_FILES
from .high_fidelity_release_readiness import HighFidelityReleaseReadinessError, inspect_release_readiness
from .reference_acceptance_policy import apply_reference_policy

SHA40 = re.compile(r"^[0-9a-f]{40}$")
QUEST_SERIAL = re.compile(r"^[A-Za-z0-9._:-]+$")
UNITY_VERSION = re.compile(r"^6000\.3\.\d+f\d+$")


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


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _acceptance_dir(result: dict[str, Any]) -> Path | None:
    value = str(result.get("physical_acceptance_dir") or "").strip()
    return Path(value).expanduser().resolve() if value else None


def _canonicalize_physical_command(result: dict[str, Any], command: str) -> str:
    acceptance = _acceptance_dir(result)
    if acceptance is None:
        return command
    acceptance_arg = _ps_literal(str(acceptance))

    if command.startswith(".\\run-windows-renderer-probe.ps1"):
        return f".\\run-reference-windows-renderer-probe.ps1 -AcceptanceDir {acceptance_arg}"
    if command.startswith(".\\run-quest-renderer-probe.ps1"):
        return f".\\run-reference-quest-renderer-probe.ps1 -AcceptanceDir {acceptance_arg}"
    if command.startswith(".\\record-renderer-acceptance.ps1"):
        if '-Platform "windows-unity-univrm"' in command:
            platform = "windows-unity-univrm"
            note = "<your physical review>"
        elif '-Platform "android-quest-class"' in command:
            platform = "android-quest-class"
            note = "<your physical headset review>"
        else:
            raise HighFidelityReleaseReadinessCliError("renderer attestation command has no canonical platform")
        return (
            f".\\record-reference-renderer-acceptance.ps1 -AcceptanceDir {acceptance_arg} "
            f'-Platform "{platform}" -ConfirmQualityChecklist -QualityNote "{note}"'
        )
    if command.startswith(".\\complete-acceptance.ps1"):
        return f".\\complete-reference-acceptance.ps1 -AcceptanceDir {acceptance_arg}"
    return command


def _quest_adb(root: Path) -> Path:
    contract_path = root / "reference-renderer" / "renderer-contract.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityReleaseReadinessCliError(f"reference renderer contract is unreadable: {contract_path}") from exc
    if not isinstance(contract, dict) or contract.get("format") != "bodyrig-reference-renderer-contract" or contract.get("version") != 1:
        raise HighFidelityReleaseReadinessCliError("reference renderer contract format/version is non-canonical")
    unity_version = str(contract.get("unity_editor_version") or "").strip()
    if not UNITY_VERSION.fullmatch(unity_version):
        raise HighFidelityReleaseReadinessCliError("reference renderer contract has an invalid Unity editor version")
    candidate = (
        Path(r"C:\Program Files\Unity\Hub\Editor")
        / unity_version
        / "Editor"
        / "Data"
        / "PlaybackEngines"
        / "AndroidPlayer"
        / "SDK"
        / "platform-tools"
        / "adb.exe"
    )
    if not candidate.is_file():
        raise HighFidelityReleaseReadinessCliError(
            f"pinned Unity Android adb is unavailable: {candidate}; run high-fidelity-rig-preflight.ps1"
        )
    return candidate.resolve()


def _normalize_quest_command(command: str, root: Path, quest_serial: str | None) -> str:
    if "run-reference-quest-renderer-probe.ps1" not in command:
        return command
    if "-AdbExe" not in command:
        command += f" -AdbExe {_ps_literal(str(_quest_adb(root)))}"
    serial = str(quest_serial or "").strip()
    if serial:
        if not QUEST_SERIAL.fullmatch(serial):
            raise HighFidelityReleaseReadinessCliError("Quest serial contains unsupported characters")
        if "-Serial" not in command:
            command += f" -Serial {_ps_literal(serial)}"
    return command


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


def _operator_command(
    result: dict[str, Any],
    command: str,
    root: Path,
    *,
    quest_serial: str | None = None,
) -> str:
    normalized = _canonicalize_physical_command(result, command)
    normalized = _normalize_quest_command(normalized, root, quest_serial)
    return _absolutize_command(normalized, root)


def _blocked_result(result: dict[str, Any], reason: str) -> dict[str, Any]:
    value = dict(result)
    value["state"] = "blocked"
    value["next_gate"] = None
    value["production_ready"] = False
    value["production_activation"] = False
    value["reference_policy"] = {"authorized": False, "reason": reason}
    return value


def _apply_reference_policy_guard(result: dict[str, Any]) -> dict[str, Any]:
    acceptance = _acceptance_dir(result)
    if acceptance is None or not acceptance.is_dir():
        return result
    try:
        status = apply_reference_policy(inspect_acceptance_dir(acceptance))
    except AcceptanceStatusError as exc:
        return _blocked_result(result, f"canonical reference-policy inspection failed: {exc}")
    if status.state == "blocked":
        return _blocked_result(result, f"{status.gate}: {status.message}")
    value = dict(result)
    value["reference_policy"] = {"authorized": True, "gate": status.gate, "state": status.state}
    return value


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


def bind_operator_checkout(
    result: dict[str, Any],
    operator_root: Path,
    *,
    quest_serial: str | None = None,
) -> dict[str, Any]:
    root = operator_root.expanduser().resolve()
    if not root.is_dir() or not (root / ".git").exists():
        raise HighFidelityReleaseReadinessCliError(f"operator root is not a BodyRig Git checkout: {root}")
    missing = tuple(name for name in CANONICAL_OPERATOR_FILES if not (root / name).is_file())
    if missing:
        raise HighFidelityReleaseReadinessCliError(
            "operator checkout is missing canonical reference dependencies: " + ", ".join(missing)
        )

    result = _apply_reference_policy_guard(result)
    if result.get("state") == "blocked":
        return result

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
            next_value["command"] = _operator_command(
                result,
                command,
                root,
                quest_serial=quest_serial,
            )
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
    parser.add_argument("--quest-serial")
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
    policy = result.get("reference_policy")
    if isinstance(policy, dict) and policy.get("authorized") is False:
        print(f"Reference policy: BLOCKED | {policy.get('reason') or 'unknown reason'}")
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
            result = bind_operator_checkout(
                result,
                args.operator_root,
                quest_serial=args.quest_serial,
            )
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
