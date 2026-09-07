from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .acceptance_status import _session_status
from .rig_window_acceptance import progress_rank
from . import rig_window_plan as base


RESCUE_RANK = 15
SESSION_RANK = 10
INTERRUPTED_ADOPT_RANK = 8
INTERRUPTED_FIT_RANK = 5


def _scope_sessions(
    root: Path,
    *,
    performer_id: str,
    resolved_performer: str,
    body_id: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sessions_root in base._session_roots(root):
        if not sessions_root.is_dir():
            continue
        for path in sessions_root.glob("*.json"):
            if path.name.endswith(".readiness.json"):
                continue
            session = base._read_json(path)
            if not session:
                continue
            if session.get("format") != "bodyrig-physical-clone-session" or session.get("version") != 1:
                continue
            if session.get("status") != "pass" or session.get("stage") != "complete":
                continue
            session_performer = str(session.get("performer_id") or "").strip()
            session_body = str(session.get("body_id") or "").strip()
            revision = str(session.get("bodyrig_revision") or "").strip().lower()
            if not base.SHA40.fullmatch(revision):
                continue
            if performer_id and session_performer != performer_id:
                continue
            if body_id and session_body != body_id:
                continue
            if not performer_id and resolved_performer and session_performer != resolved_performer:
                continue
            rows.append(
                {
                    "path": str(path.resolve()),
                    "stamp": str(session.get("completed_utc") or ""),
                    "performer_id": session_performer,
                    "body_id": session_body,
                    "revision": revision,
                }
            )

    if performer_id or resolved_performer:
        return rows
    performers = sorted({row["performer_id"] for row in rows if row["performer_id"]})
    if len(performers) > 1:
        raise base.RigWindowPlanError(
            "Standalone physical-session evidence belongs to multiple Stash performers; pass -PerformerId/-BodyId before reuse: "
            + ", ".join(performers)
        )
    return rows


def _existing_candidates(
    *,
    repo_root: Path,
    root: Path,
    rows: list[dict[str, Any]],
    performer_id: str,
    resolved_performer: str,
    body_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []

    acceptance_rows = [row for row in rows if str(row.get("acceptance_dir") or "").strip()]
    for item in base._acceptance_assessments(acceptance_rows):
        revision = str(item.get("evidence_revision") or "")
        if revision and not base.SHA40.fullmatch(revision):
            continue
        candidates.append(
            {
                "kind": "ui-acceptance",
                "rank": int(item["progress_rank"]),
                "stamp": str(item.get("stamp") or ""),
                "preferred": False,
                **item,
            }
        )

    seen_sessions: set[str] = set()
    for item in _scope_sessions(
        root,
        performer_id=performer_id,
        resolved_performer=resolved_performer,
        body_id=body_id,
    ):
        session_path = Path(item["path"])
        if str(session_path) in seen_sessions:
            continue
        seen_sessions.add(str(session_path))
        try:
            status = _session_status(session_path)
        except Exception as exc:
            rejected.append({"session_report": str(session_path), "reason": str(exc)})
            continue
        rank = progress_rank(status)
        if rank <= 0:
            rejected.append(
                {
                    "session_report": str(session_path),
                    "reason": f"structural session status is {status.state}/{status.gate}",
                }
            )
            continue
        candidates.append(
            {
                "kind": "physical-session",
                "rank": max(rank, SESSION_RANK),
                "stamp": item["stamp"],
                "preferred": False,
                "session_report": item["path"],
                "state": status.state,
                "gate": status.gate,
                "acceptance_dir": status.acceptance_dir,
                "evidence_revision": str(status.bodyrig_revision or item["revision"]).lower(),
                "performer_id": item["performer_id"],
                "body_id": item["body_id"],
            }
        )
    return candidates, rejected


def _rescue_candidates(
    rows: list[dict[str, Any]],
    *,
    preferred_job_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for row in rows:
        if row.get("status") != "failed":
            continue
        if (
            "high-fidelity Gate A failed" not in str(row.get("error") or "")
            and "high-fidelity Gate A failed" not in str(row.get("resume_source_error") or "")
        ):
            continue
        job_id = str(row.get("job_id") or "")
        if not base.JOB_ID.fullmatch(job_id):
            continue
        try:
            assessment = base.assess_body_job_resume(job_id)
        except Exception as exc:
            rejected.append({"job_id": job_id, "reason": str(exc)})
            continue
        if assessment.get("eligible") is not True or assessment.get("persistent_mutation") is not False:
            continue
        candidates.append(
            {
                "kind": "gate-a-rescue",
                "rank": RESCUE_RANK,
                "stamp": str(row.get("stamp") or ""),
                "preferred": job_id == preferred_job_id,
                "job_id": job_id,
                "body_id": str(assessment.get("body_id") or ""),
                "package_sha256": str(assessment.get("package_sha256") or ""),
                "evidence_revision": str(assessment.get("producer_revision") or row.get("bodyrig_revision") or "").lower(),
            }
        )
    return candidates, rejected


def _interrupted_candidates(
    repo_root: Path,
    rows: list[dict[str, Any]],
    *,
    preferred_job_id: str,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, str]] = []
    for row in rows:
        if row.get("status") not in {"failed", "interrupted"}:
            continue
        job_id = str(row.get("job_id") or "")
        if not base.JOB_ID.fullmatch(job_id):
            continue
        assessment = base._interrupted_assessment(repo_root, job_id)
        if not assessment:
            rejected.append({"job_id": job_id, "reason": "read-only interrupted recovery assessment unavailable"})
            continue
        if assessment.get("available") is not True or assessment.get("expensive_reconstruction_rerun") is not False:
            continue
        fitter = bool(assessment.get("fitter_rerun"))
        candidates.append(
            {
                "kind": "interrupted-body-recovery",
                "rank": INTERRUPTED_FIT_RANK if fitter else INTERRUPTED_ADOPT_RANK,
                "stamp": str(row.get("stamp") or ""),
                "preferred": job_id == preferred_job_id,
                "job_id": job_id,
                "recovery_mode": str(assessment.get("recovery_mode") or ""),
                "reconstruction_sha256": assessment.get("reconstruction_sha256"),
                "package_sha256": assessment.get("package_sha256"),
                "fitter_rerun": fitter,
                "reason": str(assessment.get("reason") or ""),
            }
        )
    return candidates, rejected


def rank_physical_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Physical progress first; explicit preferred job and recency only break ties."""
    return sorted(
        candidates,
        key=lambda item: (
            int(item.get("rank") or 0),
            bool(item.get("preferred")),
            str(item.get("stamp") or ""),
        ),
        reverse=True,
    )


def _historical_command(*, revision: str, flag: str, path: str) -> str:
    return (
        f"& .\\update-windows.ps1 -Revision {base._ps_quote(revision)} -NoBrowser; "
        f"if ($?) {{ & .\\physical-acceptance-status.ps1 {flag} {base._ps_quote(path)} }}"
    )


def _base_result(
    head: str,
    *,
    rank: int,
    path: str,
    resolved_person: str,
    resolved_performer: str,
    requested_body: str,
    state: str = "ready",
) -> dict[str, Any]:
    return {
        "format": "bodyrig-rig-window-plan",
        "version": 4,
        "read_only": True,
        "state": state,
        "priority": rank,
        "progress_rank": rank,
        "path": path,
        "bodyrig_revision": head,
        "scope": {
            "person_id": resolved_person or None,
            "performer_id": resolved_performer or None,
            "body_id": requested_body or None,
        },
    }


def build_plan(
    *,
    repo_root: Path,
    preferred_job_id: str = "",
    person_id: str = "",
    performer_id: str = "",
    body_id: str = "",
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    head = base._head(repo_root)
    root = base.data_dir()
    all_rows = base._job_rows(root)
    resolved_person, resolved_performer = base.resolve_person_scope(
        root=root,
        rows=all_rows,
        preferred_job_id=preferred_job_id,
        person_id=person_id,
        performer_id=performer_id,
    )
    rows = base._scope_rows(all_rows, person_id=resolved_person, performer_requested=bool(performer_id))
    scope_performer = resolved_performer or performer_id

    existing, rejected_existing = _existing_candidates(
        repo_root=repo_root,
        root=root,
        rows=rows,
        performer_id=performer_id,
        resolved_performer=resolved_performer,
        body_id=body_id,
    )
    rescues, rejected_rescue = _rescue_candidates(rows, preferred_job_id=preferred_job_id)
    interrupted, rejected_interrupted = _interrupted_candidates(
        repo_root,
        rows,
        preferred_job_id=preferred_job_id,
    )
    ranked = rank_physical_candidates(existing + rescues + interrupted)

    for selected in ranked:
        kind = selected["kind"]
        rank = int(selected["rank"])
        revision = str(selected.get("evidence_revision") or "").lower()

        if kind == "ui-acceptance":
            acceptance_dir = str(selected["acceptance_dir"])
            if selected.get("state") == "complete":
                result = _base_result(
                    head,
                    rank=rank,
                    path="existing-gate-a-acceptance",
                    resolved_person=resolved_person,
                    resolved_performer=scope_performer,
                    requested_body=body_id,
                    state="complete",
                )
                result.update(
                    {
                        "evidence_revision": revision,
                        "acceptance_dir": acceptance_dir,
                        "gate": selected.get("gate"),
                        "expensive_reconstruction_rerun": False,
                        "fitter_rerun": False,
                        "rationale": "The furthest valid scoped physical acceptance is already complete. Do not recompute an earlier stage.",
                        "next_command": None,
                    }
                )
                return result
            if revision != head:
                if not base._historical_revision_is_safe(repo_root, revision):
                    continue
                result = _base_result(
                    head,
                    rank=rank,
                    path="historical-acceptance-checkout",
                    resolved_person=resolved_person,
                    resolved_performer=scope_performer,
                    requested_body=body_id,
                )
                result.update(
                    {
                        "evidence_revision": revision,
                        "acceptance_dir": acceptance_dir,
                        "gate": selected.get("gate"),
                        "expensive_reconstruction_rerun": False,
                        "fitter_rerun": False,
                        "rationale": "The furthest scoped physical acceptance is historical; re-enter its exact revision instead of recomputing.",
                        "next_command": _historical_command(
                            revision=revision,
                            flag="-AcceptanceDir",
                            path=acceptance_dir,
                        ),
                    }
                )
                return result
            try:
                status = base._current_acceptance_status(Path(acceptance_dir), repo_root)
            except Exception:
                continue
            if status.state not in {"blocked", "error"} and status.next_command:
                result = _base_result(
                    head,
                    rank=rank,
                    path="existing-gate-a-acceptance",
                    resolved_person=resolved_person,
                    resolved_performer=scope_performer,
                    requested_body=body_id,
                )
                result.update(
                    {
                        "evidence_revision": revision,
                        "acceptance_dir": acceptance_dir,
                        "gate": status.gate,
                        "expensive_reconstruction_rerun": False,
                        "fitter_rerun": False,
                        "rationale": "Continue the furthest scoped physical acceptance before any earlier work.",
                        "next_command": status.next_command,
                    }
                )
                return result

        if kind == "physical-session":
            session_report = str(selected["session_report"])
            if selected.get("state") == "complete":
                result = _base_result(
                    head,
                    rank=rank,
                    path="existing-physical-session",
                    resolved_person=resolved_person,
                    resolved_performer=scope_performer,
                    requested_body=body_id or str(selected.get("body_id") or ""),
                    state="complete",
                )
                result.update(
                    {
                        "evidence_revision": revision,
                        "session_report": session_report,
                        "acceptance_dir": selected.get("acceptance_dir"),
                        "gate": selected.get("gate"),
                        "expensive_reconstruction_rerun": False,
                        "fitter_rerun": False,
                        "rationale": "The furthest scoped standalone physical session/acceptance chain is already complete.",
                        "next_command": None,
                    }
                )
                return result
            if revision != head:
                if not base._historical_revision_is_safe(repo_root, revision):
                    continue
                result = _base_result(
                    head,
                    rank=rank,
                    path="historical-physical-session-checkout",
                    resolved_person=resolved_person,
                    resolved_performer=scope_performer or str(selected.get("performer_id") or ""),
                    requested_body=body_id or str(selected.get("body_id") or ""),
                )
                result.update(
                    {
                        "evidence_revision": revision,
                        "session_report": session_report,
                        "acceptance_dir": selected.get("acceptance_dir"),
                        "gate": selected.get("gate"),
                        "expensive_reconstruction_rerun": False,
                        "fitter_rerun": False,
                        "rationale": "A completed scoped physical session exists on an older exact revision. Re-enter it instead of rerunning clone/reconstruction.",
                        "next_command": _historical_command(
                            revision=revision,
                            flag="-SessionReport",
                            path=session_report,
                        ),
                    }
                )
                return result
            try:
                status = base._current_session_status(Path(session_report), repo_root)
            except Exception:
                continue
            if status.state not in {"blocked", "error"} and status.next_command:
                result = _base_result(
                    head,
                    rank=rank,
                    path="existing-physical-session",
                    resolved_person=resolved_person,
                    resolved_performer=scope_performer or str(selected.get("performer_id") or ""),
                    requested_body=body_id or str(selected.get("body_id") or ""),
                )
                result.update(
                    {
                        "evidence_revision": revision,
                        "session_report": session_report,
                        "acceptance_dir": status.acceptance_dir,
                        "gate": status.gate,
                        "expensive_reconstruction_rerun": False,
                        "fitter_rerun": False,
                        "rationale": "Continue the furthest scoped completed physical session before any recomputation.",
                        "next_command": status.next_command,
                    }
                )
                return result

        if kind == "gate-a-rescue":
            job_id = str(selected["job_id"])
            result = _base_result(
                head,
                rank=rank,
                path="historical-gate-a-resume",
                resolved_person=resolved_person,
                resolved_performer=scope_performer,
                requested_body=body_id or str(selected.get("body_id") or ""),
            )
            result.update(
                {
                    "job_id": job_id,
                    "package_sha256": selected.get("package_sha256"),
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "No farther scoped physical acceptance exists; reuse the clone/recovery/fitter output and commit the already-validatable Gate A.",
                    "next_command": f".\\resume-body-job.ps1 -JobId {base._ps_quote(job_id)}",
                }
            )
            return result

        if kind == "interrupted-body-recovery":
            job_id = str(selected["job_id"])
            result = _base_result(
                head,
                rank=rank,
                path="interrupted-body-recovery",
                resolved_person=resolved_person,
                resolved_performer=scope_performer,
                requested_body=body_id,
            )
            result.update(
                {
                    "job_id": job_id,
                    "recovery_mode": selected.get("recovery_mode"),
                    "reconstruction_sha256": selected.get("reconstruction_sha256"),
                    "package_sha256": selected.get("package_sha256"),
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": bool(selected.get("fitter_rerun")),
                    "rationale": selected.get("reason") or "Reuse retained interrupted body evidence before reconstruction.",
                    "next_command": f".\\resume-interrupted-body-job.ps1 -JobId {base._ps_quote(job_id)}",
                }
            )
            return result

    if performer_id and body_id:
        next_command = (
            f".\\bodyrig-status.ps1 -PerformerId {base._ps_quote(performer_id)} "
            f"-BodyId {base._ps_quote(body_id)}"
        )
    else:
        next_command = ".\\bodyrig-status.ps1"
    result = _base_result(
        head,
        rank=0,
        path="fresh-profiled-physical-preflight",
        resolved_person=resolved_person,
        resolved_performer=scope_performer,
        requested_body=body_id,
    )
    result.update(
        {
            "expensive_reconstruction_rerun": True,
            "fitter_rerun": True,
            "rejected_existing_evidence_count": len(rejected_existing),
            "rejected_gate_a_resume_count": len(rejected_rescue),
            "rejected_interrupted_recovery_count": len(rejected_interrupted),
            "rationale": "No reusable scoped physical evidence validated. Only now spend rig time on fresh profiled physical preflight/reconstruction.",
            "next_command": next_command,
        }
    )
    return result


def _render_text(plan: dict[str, Any]) -> str:
    lines = [
        f"BodyRig rig-window plan: {str(plan['state']).upper()} | PROGRESS {plan['progress_rank']}",
        f"Path: {plan['path']}",
        f"Revision: {plan['bodyrig_revision']}",
    ]
    scope = plan.get("scope")
    if isinstance(scope, dict):
        lines.append(
            "Scope: "
            + f"Person={scope.get('person_id') or '-'} | "
            + f"Performer={scope.get('performer_id') or '-'} | "
            + f"Body={scope.get('body_id') or '-'}"
        )
    for key, label in (
        ("job_id", "Job"),
        ("gate", "Gate"),
        ("evidence_revision", "Evidence revision"),
        ("acceptance_dir", "Acceptance"),
        ("session_report", "Session"),
        ("recovery_mode", "Recovery mode"),
    ):
        if plan.get(key):
            lines.append(f"{label}: {plan[key]}")
    if "expensive_reconstruction_rerun" in plan:
        lines.append(
            "Expensive reconstruction rerun: "
            + str(bool(plan["expensive_reconstruction_rerun"])).lower()
            + " | fitter rerun: "
            + str(bool(plan.get("fitter_rerun"))).lower()
        )
    if plan.get("rationale"):
        lines.append(str(plan["rationale"]))
    if plan.get("next_command"):
        lines.extend(["Next command:", str(plan["next_command"])])
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Furthest-evidence-first BodyRig target-rig planner")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--preferred-job-id", default="")
    parser.add_argument("--person-id", default="")
    parser.add_argument("--performer-id", default="")
    parser.add_argument("--body-id", default="")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if bool(args.performer_id) != bool(args.body_id):
        print("BodyRig rig-window plan: ERROR | Pass --performer-id and --body-id together, or omit both.", file=sys.stderr)
        return 2
    if args.preferred_job_id and not base.JOB_ID.fullmatch(args.preferred_job_id):
        print("BodyRig rig-window plan: ERROR | preferred job id is invalid.", file=sys.stderr)
        return 2
    if args.person_id and not base.PERSON_ID.fullmatch(args.person_id):
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
        print(_render_text(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
