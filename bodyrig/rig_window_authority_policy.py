from __future__ import annotations

import json
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .acceptance_status import AcceptanceStatus
from .rig_window_acceptance import has_automatic_evidence, inspect_for_rig_window
from . import rig_window_policy as policy


COMMITTED_GATE_A_RANK = 16
_PATCH_LOCK = threading.RLock()
_ORIGINAL_EXISTING_CANDIDATES = policy._existing_candidates
_ORIGINAL_CURRENT_ACCEPTANCE_STATUS = policy.base._current_acceptance_status
_ORIGINAL_CURRENT_SESSION_STATUS = policy.base._current_session_status


def _committed_gate_a(candidate: dict[str, Any]) -> bool:
    if str(candidate.get("gate") or "") != "gate-a":
        return False
    acceptance_text = str(candidate.get("acceptance_dir") or "").strip()
    if not acceptance_text:
        return False
    try:
        acceptance_dir = Path(acceptance_text).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return False
    return (acceptance_dir / "bodyrig-acceptance.json").is_file()


def _strict_complete_historical_revision_is_safe(repo_root: Path, revision: str) -> bool:
    revision = str(revision or "").strip().lower()
    if not policy.base.SHA40.fullmatch(revision):
        return False
    branch = policy.base._git(repo_root, "rev-parse", "refs/remotes/origin/main^{commit}")
    branch_head = branch.stdout.strip().lower()
    if branch.returncode != 0 or not policy.base.SHA40.fullmatch(branch_head):
        return False
    ancestor = policy.base._git(repo_root, "merge-base", "--is-ancestor", revision, branch_head)
    return ancestor.returncode == 0


def _automatic_payload(acceptance_dir: Path) -> dict[str, Any] | None:
    if not has_automatic_evidence(acceptance_dir):
        return None
    payload = inspect_for_rig_window(acceptance_dir)
    if payload.get("policy_scope") != "evidence-revision-automatic-structural":
        return None
    return payload


def _automatic_current_status(acceptance_dir: Path, repo_root: Path) -> AcceptanceStatus | None:
    payload = _automatic_payload(acceptance_dir)
    if payload is None:
        return None
    revision = str(payload.get("bodyrig_revision") or "").strip().lower()
    head = policy.base._head(repo_root)
    if revision != head:
        raise policy.base.RigWindowPlanError(
            f"Automatic acceptance belongs to {revision or 'unknown'}, not current checkout {head}."
        )
    stage = str(payload.get("automatic_stage") or "")
    state = str(payload.get("state") or "ready")
    command = None
    if state != "complete":
        command = (
            f".\\run-automatic-production-activation.ps1 -AcceptanceDir "
            f"{policy.base._ps_quote(str(acceptance_dir))}"
        )
    return AcceptanceStatus(
        state="complete" if state == "complete" else "ready",
        gate=f"automatic-{stage}",
        acceptance_dir=str(acceptance_dir),
        body_id=str(payload.get("body_id") or "") or None,
        bodyrig_revision=revision or None,
        message=str(payload.get("message") or "Automatic production evidence is reusable."),
        next_command=command,
    )


def _guarded_current_acceptance_status(acceptance_dir: Path, repo_root: Path) -> AcceptanceStatus:
    automatic = _automatic_current_status(acceptance_dir, repo_root)
    return automatic if automatic is not None else _ORIGINAL_CURRENT_ACCEPTANCE_STATUS(acceptance_dir, repo_root)


def _guarded_current_session_status(session_path: Path, repo_root: Path) -> AcceptanceStatus:
    status = _ORIGINAL_CURRENT_SESSION_STATUS(session_path, repo_root)
    acceptance_text = str(status.acceptance_dir or "").strip()
    if acceptance_text:
        acceptance_dir = Path(acceptance_text)
        if has_automatic_evidence(acceptance_dir):
            automatic = _automatic_current_status(acceptance_dir, repo_root)
            if automatic is not None:
                return automatic
    return status


def enforce_existing_authority(
    *,
    repo_root: Path,
    candidates: list[dict[str, Any]],
    rejected: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Normalize existing-evidence rank and remove terminal unsafe history."""

    head = policy.base._head(repo_root)
    kept: list[dict[str, Any]] = []
    rejected_out = list(rejected)

    for raw in candidates:
        candidate = dict(raw)
        if _committed_gate_a(candidate):
            candidate["rank"] = max(int(candidate.get("rank") or 0), COMMITTED_GATE_A_RANK)

        acceptance_text = str(candidate.get("acceptance_dir") or "").strip()
        if candidate.get("kind") == "physical-session" and acceptance_text:
            acceptance_dir = Path(acceptance_text)
            if has_automatic_evidence(acceptance_dir):
                try:
                    automatic = _automatic_payload(acceptance_dir)
                except Exception as exc:
                    rejected_out.append(
                        {
                            "evidence": acceptance_text,
                            "reason": f"automatic standalone acceptance is not reusable: {exc}",
                        }
                    )
                    continue
                if automatic is not None:
                    candidate["rank"] = int(automatic.get("progress_rank") or 0)
                    candidate["gate"] = str(automatic.get("gate") or "")
                    candidate["state"] = str(automatic.get("state") or "ready")
                    candidate["evidence_revision"] = str(automatic.get("bodyrig_revision") or "").strip().lower()

        revision = str(candidate.get("evidence_revision") or "").strip().lower()
        if revision and revision != head and str(candidate.get("state") or "") == "complete":
            if not _strict_complete_historical_revision_is_safe(repo_root, revision):
                label = str(candidate.get("acceptance_dir") or candidate.get("session_report") or "historical evidence")
                rejected_out.append(
                    {
                        "evidence": label,
                        "reason": (
                            "complete historical evidence revision is not proven as an ancestor of the locally fetched "
                            "origin/main authority"
                        ),
                    }
                )
                continue
        kept.append(candidate)

    return kept, rejected_out


def _guarded_existing_candidates(
    *, repo_root: Path, root: Path, rows: list[dict[str, Any]], performer_id: str,
    resolved_performer: str, body_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    candidates, rejected = _ORIGINAL_EXISTING_CANDIDATES(
        repo_root=repo_root,
        root=root,
        rows=rows,
        performer_id=performer_id,
        resolved_performer=resolved_performer,
        body_id=body_id,
    )
    return enforce_existing_authority(repo_root=repo_root, candidates=candidates, rejected=rejected)


def _revision_has_resumable_automatic_tooling(repo_root: Path, revision: str) -> bool:
    for path in ("bodyrig/automatic_activation_status.py", "run-automatic-production-activation.ps1"):
        if policy.base._git(repo_root, "cat-file", "-e", f"{revision}:{path}").returncode != 0:
            return False
    return True


def _historical_update_prefix(revision: str) -> str:
    return f"& .\\update-windows.ps1 -Revision {policy.base._ps_quote(revision)} -NoBrowser"


def _historical_automatic_command(
    *, repo_root: Path, revision: str, acceptance_dir: str, stage: str,
) -> str | None:
    update = _historical_update_prefix(revision)
    quoted = policy.base._ps_quote(acceptance_dir)
    if _revision_has_resumable_automatic_tooling(repo_root, revision):
        return f"{update}; if ($?) {{ & .\\run-automatic-production-activation.ps1 -AcceptanceDir {quoted} }}"
    if stage == "quest":
        return (
            f"{update}; if ($?) {{ & .\\run-automatic-reference-quest-proof.ps1 -AcceptanceDir {quoted}; "
            f"if ($?) {{ & .\\.venv\\Scripts\\python.exe -m bodyrig.automatic_release_gate "
            f"--acceptance-dir {quoted} --repo-root . }} }}"
        )
    if stage == "release":
        return (
            f"{update}; if ($?) {{ & .\\.venv\\Scripts\\python.exe -m bodyrig.automatic_release_gate "
            f"--acceptance-dir {quoted} --repo-root . }}"
        )
    return None


def _route_automatic_plan(repo_root: Path, plan: dict[str, Any]) -> dict[str, Any]:
    gate = str(plan.get("gate") or "")
    if not gate.startswith("automatic-") or str(plan.get("state") or "") == "complete":
        return plan

    acceptance_dir = str(plan.get("acceptance_dir") or "").strip()
    revision = str(plan.get("evidence_revision") or "").strip().lower()
    stage = gate.removeprefix("automatic-")
    head = str(plan.get("bodyrig_revision") or "").strip().lower()
    routed = dict(plan)
    routed["expensive_reconstruction_rerun"] = False
    routed["fitter_rerun"] = False

    if not acceptance_dir or not policy.base.SHA40.fullmatch(revision):
        routed.update(
            state="blocked",
            path="automatic-production-resume-blocked",
            next_command=None,
            rationale="Automatic evidence was selected but its acceptance path/revision is incomplete; do not recompute earlier physical work.",
        )
        return routed

    if revision == head:
        routed["path"] = "existing-automatic-production"
        routed["next_command"] = (
            f".\\run-automatic-production-activation.ps1 -AcceptanceDir {policy.base._ps_quote(acceptance_dir)}"
        )
        routed["rationale"] = (
            "Continue the furthest validated automatic Windows/Quest production stage; already valid physical work is skipped."
        )
        return routed

    command = _historical_automatic_command(
        repo_root=repo_root, revision=revision, acceptance_dir=acceptance_dir, stage=stage,
    )
    if command is not None:
        routed["path"] = "historical-automatic-production"
        routed["next_command"] = command
        routed["rationale"] = (
            "The furthest validated automatic production evidence is historical; re-enter its exact producer revision and continue only the missing automatic stage."
        )
        return routed

    routed.update(
        state="blocked",
        path="historical-automatic-resume-blocked",
        next_command=None,
        rationale=(
            "Historical automatic Quest probe/deformation evidence is reusable, but its producer revision predates the bounded quality-only resume tooling. "
            "Do not rerun reconstruction or earlier renderer stages; this chain needs an explicit historical quality-recovery path."
        ),
    )
    return routed


@contextmanager
def _authority_guard() -> Iterator[None]:
    with _PATCH_LOCK:
        previous_existing = policy._existing_candidates
        previous_acceptance = policy.base._current_acceptance_status
        previous_session = policy.base._current_session_status
        policy._existing_candidates = _guarded_existing_candidates
        policy.base._current_acceptance_status = _guarded_current_acceptance_status
        policy.base._current_session_status = _guarded_current_session_status
        try:
            yield
        finally:
            policy._existing_candidates = previous_existing
            policy.base._current_acceptance_status = previous_acceptance
            policy.base._current_session_status = previous_session


def build_plan(**kwargs: Any) -> dict[str, Any]:
    repo_root = Path(kwargs["repo_root"]).expanduser().resolve()
    with _authority_guard():
        plan = policy.build_plan(**kwargs)
    return _route_automatic_plan(repo_root, plan)


def main(argv: list[str] | None = None) -> int:
    args = policy._parser().parse_args(argv)
    if bool(args.performer_id) != bool(args.body_id):
        print("BodyRig rig-window plan: ERROR | Pass --performer-id and --body-id together, or omit both.", file=sys.stderr)
        return 2
    if args.preferred_job_id and not policy.base.JOB_ID.fullmatch(args.preferred_job_id):
        print("BodyRig rig-window plan: ERROR | preferred job id is invalid.", file=sys.stderr)
        return 2
    if args.person_id and not policy.base.PERSON_ID.fullmatch(args.person_id):
        print("BodyRig rig-window plan: ERROR | person id is invalid.", file=sys.stderr)
        return 2
    try:
        plan = build_plan(
            repo_root=args.repo_root,
            preferred_job_id=args.preferred_job_id,
            person_id=args.person_id,
            performer_id=args.performer_id,
            body_id=args.body_id,
        )
    except Exception as exc:
        if args.json:
            print(json.dumps({"state": "error", "error": str(exc)}, ensure_ascii=False, separators=(",", ":")))
        else:
            print(f"BodyRig rig-window plan: ERROR | {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(plan, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    else:
        print(policy._render_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
