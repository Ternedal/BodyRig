from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .acceptance_status import _session_status, inspect_acceptance_dir
from .acceptance_status_cli import _bind_operator_checkout
from .reference_acceptance_policy import apply_reference_policy
from .resume_body_job import assess_body_job_resume
from .rig_window_acceptance import inspect_for_rig_window
from .storage import data_dir


SHA40 = __import__("re").compile(r"^[0-9a-f]{40}$")
JOB_ID = __import__("re").compile(r"^job-[0-9a-f]{32}$")


class RigWindowPlanError(RuntimeError):
    pass


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _stamp(job: dict[str, Any]) -> str:
    return str(job.get("completed_utc") or job.get("created_utc") or "")


def _job_rows(root: Path) -> list[dict[str, Any]]:
    jobs_root = root / "ui-jobs"
    if not jobs_root.is_dir():
        return []
    rows: list[dict[str, Any]] = []
    for directory in jobs_root.iterdir():
        if not directory.is_dir():
            continue
        job = _read_json(directory / "job.json")
        if not job or job.get("format") != "bodyrig-ui-job" or job.get("kind") != "body-build":
            continue
        rows.append(
            {
                "job_id": str(job.get("job_id") or ""),
                "person_id": str(job.get("person_id") or ""),
                "status": str(job.get("status") or ""),
                "error": str(job.get("error") or ""),
                "resume_source_error": str(job.get("resume_source_error") or ""),
                "acceptance_dir": str(job.get("acceptance_dir") or ""),
                "bodyrig_revision": str(job.get("bodyrig_revision") or "").strip().lower(),
                "stamp": _stamp(job),
            }
        )
    return rows


def _session_roots(root: Path) -> tuple[Path, ...]:
    local = str(os.environ.get("LOCALAPPDATA") or "").strip()
    artifact_base = Path(local).expanduser().resolve() if local else Path(tempfile.gettempdir()).resolve()
    values = [artifact_base / "BodyRig" / "physical-clone-sessions", root / "physical-clone-sessions"]
    unique: list[Path] = []
    for value in values:
        resolved = value.resolve()
        if resolved not in unique:
            unique.append(resolved)
    return tuple(unique)


def _completed_sessions(root: Path, *, revision: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for sessions_root in _session_roots(root):
        if not sessions_root.is_dir():
            continue
        for path in sessions_root.glob("*.json"):
            if path.name.endswith(".readiness.json"):
                continue
            session = _read_json(path)
            if not session:
                continue
            if session.get("format") != "bodyrig-physical-clone-session" or session.get("version") != 1:
                continue
            if session.get("status") != "pass" or session.get("stage") != "complete":
                continue
            if str(session.get("bodyrig_revision") or "").strip().lower() != revision:
                continue
            rows.append({"path": str(path.resolve()), "stamp": str(session.get("completed_utc") or "")})
    return sorted(rows, key=lambda item: item["stamp"], reverse=True)


def rank_acceptance_assessments(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Furthest valid physical gate first; newest evidence only breaks ties."""
    return sorted(
        list(items),
        key=lambda item: (int(item.get("progress_rank") or 0), str(item.get("stamp") or "")),
        reverse=True,
    )


def _acceptance_assessments(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    assessments: list[dict[str, Any]] = []
    for row in rows:
        acceptance_text = str(row.get("acceptance_dir") or "").strip()
        if not acceptance_text:
            continue
        acceptance_dir = Path(acceptance_text).expanduser().resolve()
        if not (acceptance_dir / "bodyrig-acceptance.json").is_file():
            continue
        try:
            value = inspect_for_rig_window(acceptance_dir)
        except Exception:
            continue
        rank = int(value.get("progress_rank") or 0)
        if value.get("state") == "error" or rank <= 0:
            continue
        assessments.append(
            {
                "job_id": str(row.get("job_id") or ""),
                "person_id": str(row.get("person_id") or ""),
                "acceptance_dir": str(acceptance_dir),
                "stamp": str(row.get("stamp") or ""),
                "state": str(value.get("state") or ""),
                "gate": str(value.get("gate") or ""),
                "evidence_revision": str(value.get("bodyrig_revision") or "").strip().lower(),
                "progress_rank": rank,
            }
        )
    return rank_acceptance_assessments(assessments)


def _git(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def _head(root: Path) -> str:
    result = _git(root, "rev-parse", "HEAD")
    value = result.stdout.strip().lower()
    if result.returncode != 0 or not SHA40.fullmatch(value):
        raise RigWindowPlanError("Could not resolve exact BodyRig checkout revision.")
    status = _git(root, "status", "--porcelain")
    if status.returncode != 0:
        raise RigWindowPlanError("Could not verify BodyRig checkout cleanliness.")
    if status.stdout.strip():
        raise RigWindowPlanError("BodyRig checkout is dirty. Rig-window planning refuses to authorize a physical next command.")
    return value


def _historical_revision_is_safe(root: Path, revision: str) -> bool:
    if not SHA40.fullmatch(revision):
        return False
    branch = _git(root, "rev-parse", "refs/remotes/origin/main^{commit}")
    branch_head = branch.stdout.strip().lower()
    if branch.returncode != 0 or not SHA40.fullmatch(branch_head):
        # update-windows.ps1 will fetch before mutation. A missing local remote ref
        # is not evidence that the accepted revision is unsafe.
        return True
    ancestor = _git(root, "merge-base", "--is-ancestor", revision, branch_head)
    return ancestor.returncode == 0


def _current_acceptance_status(acceptance_dir: Path, repo_root: Path) -> Any:
    status = inspect_acceptance_dir(acceptance_dir)
    status = apply_reference_policy(status)
    return _bind_operator_checkout(status, repo_root)


def _current_session_status(session_path: Path, repo_root: Path) -> Any:
    status = _session_status(session_path)
    status = apply_reference_policy(status)
    return _bind_operator_checkout(status, repo_root)


def _interrupted_assessment(repo_root: Path, job_id: str) -> dict[str, Any] | None:
    wrapper = repo_root / "resume-interrupted-body-job.ps1"
    if not wrapper.is_file():
        return None
    try:
        completed = subprocess.run(
            [
                "pwsh",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(wrapper),
                "-JobId",
                job_id,
                "-AssessOnly",
            ],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    try:
        value = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _base_result(head: str, *, priority: int, path: str, state: str = "ready") -> dict[str, Any]:
    return {
        "format": "bodyrig-rig-window-plan",
        "version": 2,
        "read_only": True,
        "state": state,
        "priority": priority,
        "path": path,
        "bodyrig_revision": head,
    }


def build_plan(
    *,
    repo_root: Path,
    preferred_job_id: str = "",
    performer_id: str = "",
    body_id: str = "",
) -> dict[str, Any]:
    repo_root = repo_root.expanduser().resolve()
    head = _head(repo_root)
    root = data_dir()
    rows = _job_rows(root)

    resume_rows = sorted(
        [
            row
            for row in rows
            if row["status"] == "failed"
            and (
                "high-fidelity Gate A failed" in row["error"]
                or "high-fidelity Gate A failed" in row["resume_source_error"]
            )
        ],
        key=lambda item: item["stamp"],
        reverse=True,
    )
    if preferred_job_id:
        resume_rows.sort(key=lambda item: item["job_id"] == preferred_job_id, reverse=True)

    rejected_resume: list[dict[str, str]] = []
    for row in resume_rows:
        job_id = row["job_id"]
        if not JOB_ID.fullmatch(job_id):
            continue
        try:
            assessment = assess_body_job_resume(job_id)
        except Exception as exc:
            rejected_resume.append({"job_id": job_id, "reason": str(exc)})
            continue
        if assessment.get("eligible") is True and assessment.get("persistent_mutation") is False:
            result = _base_result(head, priority=1, path="historical-gate-a-resume")
            result.update(
                {
                    "job_id": job_id,
                    "body_id": str(assessment.get("body_id") or ""),
                    "package_sha256": str(assessment.get("package_sha256") or ""),
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "Reuse the already completed clone/recovery/fitter output first; only Gate A and downstream fidelity rendering need to run.",
                    "next_command": f".\\resume-body-job.ps1 -JobId {_ps_quote(job_id)}",
                }
            )
            return result

    acceptance_rows = [row for row in rows if str(row.get("acceptance_dir") or "").strip()]
    rejected_acceptance: list[dict[str, str]] = []
    for candidate in _acceptance_assessments(acceptance_rows):
        acceptance_dir = Path(candidate["acceptance_dir"])
        if candidate["state"] == "complete":
            result = _base_result(head, priority=2, path="existing-gate-a-acceptance", state="complete")
            result.update(
                {
                    "evidence_revision": candidate["evidence_revision"],
                    "acceptance_dir": candidate["acceptance_dir"],
                    "gate": candidate["gate"],
                    "progress_rank": candidate["progress_rank"],
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "This is the furthest valid physical body acceptance chain and it is already complete. Do not start a fresh reconstruction for this body.",
                    "next_command": None,
                }
            )
            return result

        evidence_revision = candidate["evidence_revision"]
        if SHA40.fullmatch(evidence_revision) and evidence_revision != head:
            if not _historical_revision_is_safe(repo_root, evidence_revision):
                rejected_acceptance.append(
                    {
                        "acceptance_dir": candidate["acceptance_dir"],
                        "reason": "evidence revision is not reachable from current origin/main authority",
                    }
                )
                continue
            result = _base_result(head, priority=2, path="historical-acceptance-checkout")
            quoted_acceptance = _ps_quote(candidate["acceptance_dir"])
            result.update(
                {
                    "evidence_revision": evidence_revision,
                    "acceptance_dir": candidate["acceptance_dir"],
                    "gate": candidate["gate"],
                    "progress_rank": candidate["progress_rank"],
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "The furthest valid downstream physical acceptance exists on an older exact BodyRig revision. Re-enter that accepted revision before spending rig time on any earlier stage.",
                    "next_command": (
                        f"& .\\update-windows.ps1 -Revision {_ps_quote(evidence_revision)} -NoBrowser; "
                        f"if ($?) {{ & .\\physical-acceptance-status.ps1 -AcceptanceDir {quoted_acceptance} }}"
                    ),
                }
            )
            return result

        if evidence_revision != head:
            continue
        try:
            status = _current_acceptance_status(acceptance_dir, repo_root)
        except Exception as exc:
            rejected_acceptance.append({"acceptance_dir": candidate["acceptance_dir"], "reason": str(exc)})
            continue
        if status.state not in {"blocked", "error"} and status.next_command:
            result = _base_result(head, priority=2, path="existing-gate-a-acceptance")
            result.update(
                {
                    "evidence_revision": evidence_revision,
                    "acceptance_dir": candidate["acceptance_dir"],
                    "gate": status.gate,
                    "progress_rank": candidate["progress_rank"],
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "Continue the furthest valid existing Gate A acceptance chain before spending rig time on an earlier clone/reconstruction stage.",
                    "next_command": status.next_command,
                }
            )
            return result

    for session in _completed_sessions(root, revision=head):
        try:
            status = _current_session_status(Path(session["path"]), repo_root)
        except Exception:
            continue
        if status.state not in {"blocked", "error"} and status.next_command:
            result = _base_result(head, priority=3, path="existing-physical-session")
            result.update(
                {
                    "session_report": session["path"],
                    "gate": status.gate,
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "Continue the exact completed physical session before spending rig time on a new reconstruction.",
                    "next_command": status.next_command,
                }
            )
            return result

    interrupted_rows = sorted(
        [row for row in rows if row["status"] in {"failed", "interrupted"} and JOB_ID.fullmatch(row["job_id"])],
        key=lambda item: item["stamp"],
        reverse=True,
    )
    if preferred_job_id:
        interrupted_rows.sort(key=lambda item: item["job_id"] == preferred_job_id, reverse=True)
    rejected_interrupted: list[dict[str, str]] = []
    for row in interrupted_rows:
        assessment = _interrupted_assessment(repo_root, row["job_id"])
        if not assessment:
            rejected_interrupted.append({"job_id": row["job_id"], "reason": "read-only interrupted recovery assessment unavailable"})
            continue
        if assessment.get("available") is True and assessment.get("expensive_reconstruction_rerun") is False:
            result = _base_result(head, priority=4, path="interrupted-body-recovery")
            result.update(
                {
                    "job_id": row["job_id"],
                    "recovery_mode": str(assessment.get("recovery_mode") or ""),
                    "reconstruction_sha256": assessment.get("reconstruction_sha256"),
                    "package_sha256": assessment.get("package_sha256"),
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": bool(assessment.get("fitter_rerun")),
                    "rationale": str(assessment.get("reason") or "Reuse retained interrupted body evidence before reconstruction."),
                    "next_command": f".\\resume-interrupted-body-job.ps1 -JobId {_ps_quote(row['job_id'])}",
                }
            )
            return result

    if performer_id and body_id:
        next_command = f".\\bodyrig-status.ps1 -PerformerId {_ps_quote(performer_id)} -BodyId {_ps_quote(body_id)}"
    else:
        next_command = ".\\bodyrig-status.ps1"
    result = _base_result(head, priority=5, path="fresh-profiled-physical-preflight")
    result.update(
        {
            "expensive_reconstruction_rerun": True,
            "fitter_rerun": True,
            "rejected_gate_a_resume_count": len(rejected_resume),
            "rejected_acceptance_count": len(rejected_acceptance),
            "rejected_interrupted_recovery_count": len(rejected_interrupted),
            "rationale": "No reusable Gate-A rescue, downstream acceptance, completed physical session or interrupted reconstruction/package recovery validated. Only now spend rig time on fresh profiled physical preflight/reconstruction.",
            "next_command": next_command,
        }
    )
    return result


def _render_text(plan: dict[str, Any]) -> str:
    lines = [
        f"BodyRig rig-window plan: {str(plan['state']).upper()} | PRIORITY {plan['priority']}",
        f"Path: {plan['path']}",
        f"Revision: {plan['bodyrig_revision']}",
    ]
    for key, label in (
        ("job_id", "Job"),
        ("gate", "Gate"),
        ("evidence_revision", "Evidence revision"),
        ("acceptance_dir", "Acceptance"),
        ("session_report", "Session"),
        ("recovery_mode", "Recovery mode"),
    ):
        value = plan.get(key)
        if value:
            lines.append(f"{label}: {value}")
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
    parser = argparse.ArgumentParser(description="Reuse-first BodyRig target-rig window planner")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--preferred-job-id", default="")
    parser.add_argument("--performer-id", default="")
    parser.add_argument("--body-id", default="")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if bool(args.performer_id) != bool(args.body_id):
        print("BodyRig rig-window plan: ERROR | Pass --performer-id and --body-id together, or omit both.", file=sys.stderr)
        return 2
    if args.preferred_job_id and not JOB_ID.fullmatch(args.preferred_job_id):
        print("BodyRig rig-window plan: ERROR | preferred job id is invalid.", file=sys.stderr)
        return 2
    try:
        plan = build_plan(
            repo_root=args.repo_root,
            preferred_job_id=args.preferred_job_id,
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
