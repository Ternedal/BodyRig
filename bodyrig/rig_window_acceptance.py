from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterator

from .acceptance_status import AcceptanceStatus, AcceptanceStatusError, _read_json, _validate_gate_a, inspect_acceptance_dir
from .automatic_activation_status import inspect_automatic_activation
from .automatic_release_gate import AutomaticReleaseGateError
from .renderer_human_rejection import any_rejection_exists


# Higher means farther through the expensive/physical acceptance chain.
# This intentionally describes the evidence revision's own structural state;
# current-checkout renderer policy is applied only after the exact evidence
# revision has been selected/re-entered.
GATE_PROGRESS = {
    "gate-a": 10,
    "windows-probe": 20,
    "windows-attestation": 30,
    "quest-probe": 40,
    "quest-attestation": 50,
    "release": 60,
}

# Automatic stages describe the next missing stage. Ranks align with the
# equivalent amount of already-preserved physical renderer work in the legacy
# chain. Gate-A-only automatic eligibility is deliberately 16 so committed Gate
# A remains above a merely validatable rescue (15).
AUTOMATIC_STAGE_PROGRESS = {
    "windows": 16,
    "quest": 40,
    "quest-quality": 50,
    "release": 60,
    "complete": 100,
}


def progress_rank(status: AcceptanceStatus) -> int:
    if status.state == "complete":
        return 100
    if status.state == "blocked":
        return 0
    return GATE_PROGRESS.get(status.gate, 0)


def has_automatic_evidence(acceptance_dir: str | Path) -> bool:
    directory = Path(acceptance_dir).expanduser().resolve()
    if (directory / "windows-evidence" / "windows-deformation-quality.json").exists():
        return True
    if (directory / "quest-evidence" / "quest-deformation-quality.json").exists():
        return True
    release = directory / "bodyrig-release-acceptance.json"
    if not release.is_file():
        return False
    try:
        value = _read_json(release, "Release acceptance")
    except AcceptanceStatusError:
        # An unreadable release in an otherwise automatic directory must not be
        # silently reinterpreted through the legacy release-v1 path.
        return True
    return value.get("format") == "bodyrig-release-acceptance" and value.get("version") == 2


def has_legacy_human_attestation(acceptance_dir: str | Path) -> bool:
    directory = Path(acceptance_dir).expanduser().resolve()
    return any(
        (directory / name).exists()
        for name in (
            "bodyrig-renderer-acceptance-windows.json",
            "bodyrig-renderer-acceptance-quest.json",
        )
    )


def _git_show(repo_root: Path, revision: str, path: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "show", f"{revision}:{path}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    except OSError as exc:
        raise AcceptanceStatusError("Git executable unavailable for historical automatic evidence inspection.") from exc
    if result.returncode != 0:
        raise AcceptanceStatusError(
            f"Producer revision {revision} does not expose required automatic renderer contract: {path}"
        )
    return result.stdout


@contextmanager
def _producer_contract_root(acceptance_dir: Path) -> Iterator[Path]:
    gate = _validate_gate_a(acceptance_dir / "bodyrig-acceptance.json")
    checkout = Path(__file__).resolve().parents[1]
    raw = _git_show(checkout, gate.revision, "reference-renderer/renderer-contract.json")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AcceptanceStatusError(
            f"Producer revision {gate.revision} renderer contract is invalid JSON."
        ) from exc
    if not isinstance(value, dict):
        raise AcceptanceStatusError(
            f"Producer revision {gate.revision} renderer contract is not a JSON object."
        )
    with tempfile.TemporaryDirectory(prefix="bodyrig-rig-window-auto-contract-") as temporary:
        root = Path(temporary)
        contract = root / "reference-renderer" / "renderer-contract.json"
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        yield root


def _inspect_automatic_structural(acceptance_dir: Path) -> dict[str, Any]:
    try:
        with _producer_contract_root(acceptance_dir) as producer_root:
            status = inspect_automatic_activation(
                acceptance_dir,
                producer_root,
                require_git_state=False,
            )
    except (AutomaticReleaseGateError, AcceptanceStatusError, OSError, ValueError) as exc:
        raise AcceptanceStatusError(f"Automatic production evidence is not reusable: {exc}") from exc

    rank = AUTOMATIC_STAGE_PROGRESS.get(status.stage, 0)
    if rank <= 0:
        raise AcceptanceStatusError(f"Automatic production stage is unsupported for rig-window reuse: {status.stage}")
    return {
        "state": "complete" if status.state == "complete" else "ready",
        "gate": f"automatic-{status.stage}",
        "acceptance_dir": status.acceptance_dir,
        "body_id": status.body_id,
        "bodyrig_revision": status.bodyrig_revision,
        "message": status.message,
        "next_command": None,
        "progress_rank": rank,
        "read_only": True,
        "policy_scope": "evidence-revision-automatic-structural",
        "automatic_stage": status.stage,
    }


def inspect_for_rig_window(path: str | Path) -> dict[str, Any]:
    acceptance_dir = Path(path).expanduser().resolve()
    if any_rejection_exists(acceptance_dir):
        status = inspect_acceptance_dir(acceptance_dir)
        payload = asdict(status)
        payload["progress_rank"] = progress_rank(status)
        payload["read_only"] = True
        payload["policy_scope"] = "evidence-revision-structural"
        return payload
    if has_automatic_evidence(acceptance_dir):
        return _inspect_automatic_structural(acceptance_dir)

    status = inspect_acceptance_dir(acceptance_dir)
    payload = asdict(status)
    payload["progress_rank"] = progress_rank(status)
    payload["read_only"] = True
    payload["policy_scope"] = "evidence-revision-structural"
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect one BodyRig acceptance for reuse-first rig-window ranking without rebinding it to current operator policy."
    )
    parser.add_argument("acceptance_dir", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        payload = inspect_for_rig_window(args.acceptance_dir)
    except (AcceptanceStatusError, AutomaticReleaseGateError) as exc:
        print(
            json.dumps(
                {"state": "error", "error": str(exc), "read_only": True},
                ensure_ascii=False,
                separators=(",", ":"),
            )
        )
        return 2
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
