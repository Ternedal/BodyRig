from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .acceptance_status import AcceptanceStatusError, _session_status
from .rig_window_acceptance import inspect_for_rig_window, progress_rank


SHA40 = re.compile(r"^[0-9a-f]{40}$")
AUTHORITY_FORMAT = "bodyrig-one-command-production-authority"
AUTHORITY_VERSION = 1


class AutomaticRunDiscoveryError(RuntimeError):
    pass


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise AutomaticRunDiscoveryError(f"one-command run authority is missing or symlinked: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AutomaticRunDiscoveryError(f"one-command run authority is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise AutomaticRunDiscoveryError(f"one-command run authority must be a JSON object: {path}")
    return value


def _same_path(actual: str, expected: Path, label: str) -> Path:
    if not str(actual or "").strip():
        raise AutomaticRunDiscoveryError(f"one-command run authority is missing {label}")
    try:
        resolved = Path(str(actual)).expanduser().resolve(strict=False)
        expected_resolved = expected.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise AutomaticRunDiscoveryError(f"one-command run authority has invalid {label}") from exc
    if resolved != expected_resolved:
        raise AutomaticRunDiscoveryError(
            f"one-command run authority {label} is not the canonical path under its RunRoot: {resolved}"
        )
    return resolved


def inspect_run_authority(run_root: str | Path) -> dict[str, Any]:
    root = Path(run_root).expanduser().resolve(strict=False)
    if root.is_symlink() or not root.is_dir():
        raise AutomaticRunDiscoveryError(f"one-command RunRoot is missing or symlinked: {root}")
    authority_path = root / "run-authority.json"
    authority = _read_json(authority_path)
    if authority.get("format") != AUTHORITY_FORMAT or authority.get("version") != AUTHORITY_VERSION:
        raise AutomaticRunDiscoveryError("one-command run authority format/version mismatch")

    revision = str(authority.get("bodyrig_revision") or "").strip().lower()
    if not SHA40.fullmatch(revision):
        raise AutomaticRunDiscoveryError("one-command run authority has no canonical BodyRig revision")
    performer_id = str(authority.get("performer_id") or "").strip()
    body_id = str(authority.get("requested_body_alias") or "").strip()
    if not performer_id or not body_id:
        raise AutomaticRunDiscoveryError("one-command run authority is missing performer/body scope")
    started_at = str(authority.get("started_at") or "").strip()
    if not started_at:
        raise AutomaticRunDiscoveryError("one-command run authority has no started_at timestamp")

    clone_output = _same_path(str(authority.get("clone_output") or ""), root / "clone-output", "clone_output")
    session_report = _same_path(
        str(authority.get("session_report") or ""),
        root / "bodyrig-physical-clone-session.json",
        "session_report",
    )
    acceptance_dir = _same_path(
        str(authority.get("acceptance_dir") or ""),
        clone_output / "acceptance",
        "acceptance_dir",
    )

    return {
        "run_root": str(root),
        "authority_path": str(authority_path),
        "revision": revision,
        "performer_id": performer_id,
        "body_id": body_id,
        "started_at": started_at,
        "completed_at": str(authority.get("completed_at") or "").strip(),
        "session_report": str(session_report),
        "clone_output": str(clone_output),
        "acceptance_dir": str(acceptance_dir),
        # This flag is informational only. Discovery never trusts it as PASS.
        "declared_production_activation": authority.get("production_activation") is True,
    }


def default_run_roots(data_root: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    artifact_base = Path(local).expanduser().resolve() if local else Path(tempfile.gettempdir()).resolve()
    for candidate in (artifact_base / "BodyRig" / "automatic-production", data_root / "automatic-production"):
        resolved = candidate.expanduser().resolve(strict=False)
        if resolved not in roots:
            roots.append(resolved)
    return tuple(roots)


def discover_run_authorities(data_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    rows: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    seen: set[Path] = set()
    for parent in default_run_roots(data_root):
        if not parent.is_dir() or parent.is_symlink():
            continue
        try:
            children = sorted(parent.iterdir(), key=lambda item: item.name)
        except OSError as exc:
            rejected.append({"run_root": str(parent), "reason": f"could not enumerate automatic-production root: {exc}"})
            continue
        for child in children:
            try:
                resolved = child.resolve(strict=False)
            except (OSError, RuntimeError):
                continue
            if resolved in seen or child.is_symlink() or not child.is_dir():
                continue
            seen.add(resolved)
            if not (child / "run-authority.json").exists():
                continue
            try:
                rows.append(inspect_run_authority(child))
            except AutomaticRunDiscoveryError as exc:
                rejected.append({"run_root": str(resolved), "reason": str(exc)})
    return rows, rejected


def candidate_from_run(run: dict[str, Any]) -> dict[str, Any] | None:
    session_path = Path(str(run["session_report"]))
    if not session_path.is_file() or session_path.is_symlink():
        # No canonical completed clone authority exists yet. Partial clone work
        # belongs to the clone/recovery system, not this run-authority index.
        return None
    try:
        session = _session_status(session_path)
    except AcceptanceStatusError as exc:
        raise AutomaticRunDiscoveryError(f"one-command physical session is invalid: {exc}") from exc
    revision = str(session.bodyrig_revision or "").strip().lower()
    if revision != str(run["revision"]):
        raise AutomaticRunDiscoveryError("one-command session revision does not match run authority")
    if str(session.body_id or "") != str(run["body_id"]):
        raise AutomaticRunDiscoveryError("one-command session body_id does not match requested_body_alias")

    acceptance_dir = Path(str(run["acceptance_dir"]))
    gate_a = acceptance_dir / "bodyrig-acceptance.json"
    if gate_a.is_file() and not gate_a.is_symlink():
        try:
            structural = inspect_for_rig_window(acceptance_dir)
        except Exception as exc:
            raise AutomaticRunDiscoveryError(f"one-command acceptance is not reusable: {exc}") from exc
        rank = int(structural.get("progress_rank") or 0)
        if rank <= 0:
            raise AutomaticRunDiscoveryError("one-command acceptance has no reusable physical progress")
        evidence_revision = str(structural.get("bodyrig_revision") or "").strip().lower()
        if evidence_revision != str(run["revision"]):
            raise AutomaticRunDiscoveryError("one-command acceptance revision does not match run authority")
        state = str(structural.get("state") or "ready")
        gate = str(structural.get("gate") or "")
    else:
        rank = max(progress_rank(session), 10)
        if rank <= 0:
            raise AutomaticRunDiscoveryError("one-command physical session has no reusable progress")
        evidence_revision = revision
        state = str(session.state)
        gate = str(session.gate)

    return {
        "kind": "physical-session",
        "rank": rank,
        "stamp": str(run.get("completed_at") or run.get("started_at") or ""),
        "preferred": False,
        "session_report": str(session_path.resolve()),
        "acceptance_dir": str(acceptance_dir.resolve(strict=False)),
        "state": state,
        "gate": gate,
        "evidence_revision": evidence_revision,
        "performer_id": str(run["performer_id"]),
        "body_id": str(run["body_id"]),
        "automatic_run_root": str(run["run_root"]),
    }
