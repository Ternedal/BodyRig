from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import asdict, replace
from pathlib import Path

from .acceptance_status import (
    AcceptanceStatus,
    AcceptanceStatusError,
    SHA40,
    _session_status,
    inspect_acceptance_dir,
)
from .reference_acceptance_policy import apply_reference_policy


CANONICAL_OPERATOR_SCRIPTS = (
    "accept-physical-clone.ps1",
    "run-reference-windows-renderer-probe.ps1",
    "record-reference-renderer-acceptance.ps1",
    "run-reference-quest-renderer-probe.ps1",
    "complete-reference-acceptance.ps1",
)
CANONICAL_OPERATOR_FILES = CANONICAL_OPERATOR_SCRIPTS + (
    "run-windows-renderer-probe.ps1",
    "record-renderer-acceptance.ps1",
    "run-quest-renderer-probe.ps1",
    "complete-acceptance.ps1",
    "reference-renderer/renderer-contract.json",
    "reference-renderer/build-reference-renderer.ps1",
    "reference-renderer/ProjectSettings/ProjectVersion.txt",
    "reference-renderer/Packages/manifest.json",
)
ACTIONABLE_GATES = {
    "gate-a",
    "windows-probe",
    "windows-attestation",
    "quest-probe",
    "quest-attestation",
    "release",
}


def _quote(path: str) -> str:
    return f'"{path}"'


def _script_invocation(name: str, operator_root: Path | None) -> str:
    if operator_root is None:
        return f".\\{name}"
    return f"& {_quote(str((operator_root / name).resolve()))}"


def _operator_command(status: AcceptanceStatus, operator_root: Path | None = None) -> AcceptanceStatus:
    if not status.acceptance_dir:
        return _absolutize_existing_command(status, operator_root)
    if status.gate == "windows-probe":
        return replace(
            status,
            next_command=(
                f"{_script_invocation('run-reference-windows-renderer-probe.ps1', operator_root)} "
                f"-AcceptanceDir {_quote(status.acceptance_dir)}"
            ),
        )
    if status.gate == "windows-attestation":
        return replace(
            status,
            next_command=(
                f"{_script_invocation('record-reference-renderer-acceptance.ps1', operator_root)} "
                f"-AcceptanceDir {_quote(status.acceptance_dir)} "
                '-Platform "windows-unity-univrm" '
                '-QualityNote "<your physical review>"'
            ),
        )
    if status.gate == "quest-probe":
        return replace(
            status,
            next_command=(
                f"{_script_invocation('run-reference-quest-renderer-probe.ps1', operator_root)} "
                f"-AcceptanceDir {_quote(status.acceptance_dir)}"
            ),
        )
    if status.gate == "quest-attestation":
        return replace(
            status,
            next_command=(
                f"{_script_invocation('record-reference-renderer-acceptance.ps1', operator_root)} "
                f"-AcceptanceDir {_quote(status.acceptance_dir)} "
                '-Platform "android-quest-class" '
                '-QualityNote "<your physical headset review>"'
            ),
        )
    if status.gate == "release" and status.state == "ready":
        return replace(
            status,
            next_command=(
                f"{_script_invocation('complete-reference-acceptance.ps1', operator_root)} "
                f"-AcceptanceDir {_quote(status.acceptance_dir)}"
            ),
        )
    return _absolutize_existing_command(status, operator_root)


def _absolutize_existing_command(status: AcceptanceStatus, operator_root: Path | None) -> AcceptanceStatus:
    if operator_root is None or not status.next_command:
        return status
    for name in CANONICAL_OPERATOR_SCRIPTS:
        prefix = f".\\{name}"
        if status.next_command.startswith(prefix):
            return replace(
                status,
                next_command=_script_invocation(name, operator_root) + status.next_command[len(prefix):],
            )
    return status


def _operator_files_present(root: Path) -> tuple[bool, tuple[str, ...]]:
    missing = tuple(name for name in CANONICAL_OPERATOR_FILES if not (root / name).is_file())
    return not missing, missing


def _auto_operator_root() -> Path | None:
    candidate = Path(__file__).resolve().parents[1]
    if not (candidate / ".git").exists():
        return None
    complete, _ = _operator_files_present(candidate)
    return candidate if complete else None


def _resolve_operator_root(explicit: Path | None) -> Path | None:
    if explicit is None:
        return _auto_operator_root()
    root = explicit.expanduser().resolve()
    if not root.is_dir():
        raise AcceptanceStatusError(f"BodyRig operator root not found: {root}")
    if not (root / ".git").exists():
        raise AcceptanceStatusError(f"BodyRig operator root is not a Git checkout: {root}")
    complete, missing = _operator_files_present(root)
    if not complete:
        raise AcceptanceStatusError(
            "BodyRig operator root is missing canonical operator dependencies: " + ", ".join(missing)
        )
    return root


def _git_checkout_state(root: Path) -> tuple[str, bool]:
    try:
        head_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        status_result = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as exc:
        raise AcceptanceStatusError("Git executable unavailable for BodyRig operator checkout validation.") from exc

    head = head_result.stdout.strip().lower()
    if head_result.returncode != 0 or not SHA40.fullmatch(head):
        raise AcceptanceStatusError(f"Could not resolve exact BodyRig operator checkout revision: {root}")
    if status_result.returncode != 0:
        raise AcceptanceStatusError(f"Could not inspect BodyRig operator checkout cleanliness: {root}")
    return head, not bool(status_result.stdout.strip())


def _needs_operator_checkout(status: AcceptanceStatus) -> bool:
    if status.state in {"blocked", "complete"}:
        return False
    return status.gate in ACTIONABLE_GATES or status.next_command is not None


def _bind_operator_checkout(status: AcceptanceStatus, explicit_root: Path | None) -> AcceptanceStatus:
    if not _needs_operator_checkout(status):
        return status

    root = _resolve_operator_root(explicit_root)
    if root is None:
        return replace(
            status,
            next_command=None,
            message=(
                status.message
                + " Inspection-only: no complete BodyRig Git checkout with canonical operator dependencies is available. "
                "Run the status checker from the exact BodyRig checkout or pass --operator-root <checkout> "
                "to receive an executable next command."
            ),
        )

    head, clean = _git_checkout_state(root)
    expected = (status.bodyrig_revision or "").lower()
    if not expected or not SHA40.fullmatch(expected):
        return replace(
            status,
            state="blocked",
            gate="operator-checkout",
            next_command=None,
            message="Acceptance status has no canonical BodyRig revision; refusing to authorize a physical next command.",
        )
    if head != expected:
        return replace(
            status,
            state="blocked",
            gate="operator-checkout",
            next_command=None,
            message=(
                f"BodyRig operator checkout revision {head} does not match acceptance revision {expected}. "
                "Checkout the exact accepted revision before continuing physical acceptance."
            ),
        )
    if not clean:
        return replace(
            status,
            state="blocked",
            gate="operator-checkout",
            next_command=None,
            message=(
                "BodyRig operator checkout is dirty. Physical acceptance commands require the exact clean "
                f"accepted revision {head}."
            ),
        )
    return _operator_command(status, root)


def _status_exit_code(status: AcceptanceStatus) -> int:
    return 3 if status.state == "blocked" else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only BodyRig physical acceptance status checker")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--session-report", type=Path, help="bodyrig-physical-clone-session JSON")
    inputs.add_argument("--acceptance-dir", type=Path, help="Gate A acceptance directory")
    parser.add_argument(
        "--operator-root",
        type=Path,
        help="BodyRig Git checkout used only to validate and render the executable next operator command",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable status JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        status = _session_status(args.session_report) if args.session_report else inspect_acceptance_dir(args.acceptance_dir)
        status = apply_reference_policy(status)
        status = _bind_operator_checkout(status, args.operator_root)
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
    return _status_exit_code(status)


if __name__ == "__main__":
    raise SystemExit(main())
