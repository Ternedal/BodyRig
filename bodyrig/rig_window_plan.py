from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .acceptance_status import _session_status, inspect_acceptance_dir
from .acceptance_status_cli import _bind_operator_checkout
from .person_profiles import list_profiles
from .reference_acceptance_policy import apply_reference_policy
from .resume_body_job import assess_body_job_resume
from .rig_window_acceptance import inspect_for_rig_window
from .storage import data_dir


SHA40 = re.compile(r"^[0-9a-f]{40}$")
JOB_ID = re.compile(r"^job-[0-9a-f]{32}$")
PERSON_ID = re.compile(r"^person-[0-9a-f]{32}$")


class RigWindowPlanError(RuntimeError):
    pass


def _is_v1(value: Any) -> bool:
    return not isinstance(value, bool) and value == 1


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


def _profiles(root: Path) -> list[dict[str, Any]]:
    try:
        return list_profiles(root / "people")
    except Exception as exc:
        raise RigWindowPlanError(f"Could not validate BodyRig Person profiles for rig-window scope: {exc}") from exc


def _profile_performer(profile: dict[str, Any]) -> str:
    source = profile.get("source")
    if not isinstance(source, dict) or source.get("kind") != "stash-performer":
        return ""
    return str(source.get("performer_id") or "").strip()


def resolve_person_scope(
    *,
    root: Path,
    rows: list[dict[str, Any]],
    preferred_job_id: str = "",
    person_id: str = "",
    performer_id: str = "",
) -> tuple[str, str]:
    """Resolve UI-job scope without guessing across multiple Persons.

    Returns `(resolved_person_id, resolved_performer_id)`. Empty person id means
    there is no matching canonical Person yet; in that case UI evidence is not
    reused for an explicitly requested performer.
    """

    profiles = _profiles(root)
    by_id = {str(item.get("person_id") or ""): item for item in profiles}
    preferred_person = ""
    if preferred_job_id:
        preferred = next((row for row in rows if row.get("job_id") == preferred_job_id), None)
        if preferred:
            preferred_person = str(preferred.get("person_id") or "")

    if person_id:
        if not PERSON_ID.fullmatch(person_id):
            raise RigWindowPlanError("PersonId is not a canonical BodyRig Person id.")
        profile = by_id.get(person_id)
        if profile is None:
            raise RigWindowPlanError(f"Requested PersonId does not exist in the canonical Person library: {person_id}")
        bound_performer = _profile_performer(profile)
        if performer_id and bound_performer != performer_id:
            raise RigWindowPlanError(
                f"Requested PersonId {person_id} is bound to performer {bound_performer or 'none'}, not {performer_id}."
            )
        return person_id, performer_id or bound_performer

    if performer_id:
        matches = [profile for profile in profiles if _profile_performer(profile) == performer_id]
        match_ids = [str(profile.get("person_id") or "") for profile in matches]
        if preferred_person and preferred_person in match_ids:
            return preferred_person, performer_id
        if len(match_ids) == 1:
            return match_ids[0], performer_id
        if len(match_ids) > 1:
            raise RigWindowPlanError(
                "Multiple BodyRig Persons are bound to the requested Stash performer; pass -PersonId explicitly: "
                + ", ".join(sorted(match_ids))
            )
        return "", performer_id

    if preferred_person:
        profile = by_id.get(preferred_person)
        return preferred_person, _profile_performer(profile) if profile else ""

    job_people = sorted({str(row.get("person_id") or "") for row in rows if PERSON_ID.fullmatch(str(row.get("person_id") or ""))})
    if len(job_people) > 1:
        raise RigWindowPlanError(
            "Rig-window evidence belongs to multiple BodyRig Persons; pass -PersonId or -PerformerId to avoid cross-Person reuse: "
            + ", ".join(job_people)
        )
    if len(job_people) == 1:
        profile = by_id.get(job_people[0])
        return job_people[0], _profile_performer(profile) if profile else ""
    return "", ""


def _scope_rows(rows: list[dict[str, Any]], *, person_id: str, performer_requested: bool) -> list[dict[str, Any]]:
    if person_id:
        return [row for row in rows if row.get("person_id") == person_id]
    if performer_requested:
        # Explicit performer with no canonical Person match must never inherit
        # some other Person's old UI job merely because it is newer/further.
        return []
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


def _completed_sessions(
    root: Path,
    *,
    revision: str,
    performer_id: str = "",
    body_id: str = "",
) -> list[dict[str, str]]:
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
            if session.get("format") != "bodyrig-physical-clone-session" or not _is_v1(session.get("version")):
                continue
            if session.get("status") != "pass" or session.get("stage") != "complete":
                continue
            if str(session.get("bodyrig_revision") or "").strip().lower() != revision:
                continue
            session_performer = str(session.get("performer_id") or "")
            session_body = str(session.get("body_id") or "")
            if performer_id and session_performer != performer_id:
                continue
            if body_id and session_body != body_id:
                continue
            rows.append(
                {
                    "path": str(path.resolve()),
                    "stamp": str(session.get("completed_utc") or ""),
                    "performer_id": session_performer,
                    "body_id": session_body,
                }
            )
    return sorted(rows, key=lambda item: item["stamp"], reverse=True)


def _scoped_completed_sessions(
    root: Path,
    *,
    revision: str,
    explicit_performer_id: str,
    resolved_performer_id: str,
    body_id: str,
) -> list[dict[str, str]]:
    # An explicit performer/body pair is authoritative for standalone evidence.
    if explicit_performer_id and body_id:
        return _completed_sessions(
            root,
            revision=revision,
            performer_id=explicit_performer_id,
            body_id=body_id,
        )

    all_rows = _completed_sessions(root, revision=revision)
    if not explicit_performer_id and not body_id and len(all_rows) == 1:
        return all_rows

    # Person profiles bind performer but not standalone BodyId aliases. We may
    # narrow to the performer, but only reuse when that leaves exactly one
    # completed session; otherwise require explicit -BodyId.
    if resolved_performer_id:
        matches = [row for row in all_rows if row["performer_id"] == resolved_performer_id]
        return matches if len(matches) == 1 else []
    return []


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
    return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)


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
        # update-windows.ps1 fetches fresh authority before any mutation.
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


def _base_result(
    head: str,
    *,
    priority: int,
    path: str,
    state: str = "ready",
    person_id: str = "",
    performer_id: str = "",
    body_id: str = "",
) -> dict[str, Any]:
    return {
        "format": "bodyrig-rig-window-plan",
        "version": 3,
        "read_only": True,
        "state": state,
        "priority": priority,
        "path": path,
        "bodyrig_revision": head,
        "scope": {
            "person_id": person_id or None,
            "performer_id": performer_id or None,
            "body_id": body_id or None,
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
    head = _head(repo_root)
    root = data_dir()
    all_rows = _job_rows(root)
    resolved_person, resolved_performer = resolve_person_scope(
        root=root,
        rows=all_rows,
        preferred_job_id=preferred_job_id,
        person_id=person_id,
        performer_id=performer_id,
    )
    rows = _scope_rows(all_rows, person_id=resolved_person, performer_requested=bool(performer_id))

    def result_base(*, priority: int, path: str, state: str = "ready") -> dict[str, Any]:
        return _base_result(
            head,
            priority=priority,
            path=path,
            state=state,
            person_id=resolved_person,
            performer_id=resolved_performer or performer_id,
            body_id=body_id,
        )

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
        job_id_value = row["job_id"]
        if not JOB_ID.fullmatch(job_id_value):
            continue
        try:
            assessment = assess_body_job_resume(job_id_value)
        except Exception as exc:
            rejected_resume.append({"job_id": job_id_value, "reason": str(exc)})
            continue
        if assessment.get("eligible") is True and assessment.get("persistent_mutation") is False:
            result = result_base(priority=1, path="historical-gate-a-resume")
            result.update(
                {
                    "job_id": job_id_value,
                    "body_id": str(assessment.get("body_id") or ""),
                    "package_sha256": str(assessment.get("package_sha256") or ""),
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "Reuse the already completed clone/recovery/fitter output for the scoped Person; only Gate A and downstream fidelity rendering need to run.",
                    "next_command": f".\\resume-body-job.ps1 -JobId {_ps_quote(job_id_value)}",
                }
            )
            return result

    acceptance_rows = [row for row in rows if str(row.get("acceptance_dir") or "").strip()]
    rejected_acceptance: list[dict[str, str]] = []
    for candidate in _acceptance_assessments(acceptance_rows):
        acceptance_dir = Path(candidate["acceptance_dir"])
        if candidate["state"] == "complete":
            result = result_base(priority=2, path="existing-gate-a-acceptance", state="complete")
            result.update(
                {
                    "evidence_revision": candidate["evidence_revision"],
                    "acceptance_dir": candidate["acceptance_dir"],
                    "gate": candidate["gate"],
                    "progress_rank": candidate["progress_rank"],
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "This is the furthest valid physical body acceptance chain for the scoped Person and it is already complete. Do not start a fresh reconstruction.",
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
            result = result_base(priority=2, path="historical-acceptance-checkout")
            quoted_acceptance = _ps_quote(candidate["acceptance_dir"])
            result.update(
                {
                    "evidence_revision": evidence_revision,
                    "acceptance_dir": candidate["acceptance_dir"],
                    "gate": candidate["gate"],
                    "progress_rank": candidate["progress_rank"],
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "The furthest valid downstream physical acceptance for the scoped Person exists on an older exact BodyRig revision. Re-enter it before spending rig time on an earlier stage.",
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
            result = result_base(priority=2, path="existing-gate-a-acceptance")
            result.update(
                {
                    "evidence_revision": evidence_revision,
                    "acceptance_dir": candidate["acceptance_dir"],
                    "gate": status.gate,
                    "progress_rank": candidate["progress_rank"],
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "Continue the furthest valid existing acceptance for the scoped Person before spending rig time on an earlier clone/reconstruction stage.",
                    "next_command": status.next_command,
                }
            )
            return result

    sessions = _scoped_completed_sessions(
        root,
        revision=head,
        explicit_performer_id=performer_id,
        resolved_performer_id=resolved_performer,
        body_id=body_id,
    )
    for session in sessions:
        try:
            status = _current_session_status(Path(session["path"]), repo_root)
        except Exception:
            continue
        if status.state not in {"blocked", "error"} and status.next_command:
            result = result_base(priority=3, path="existing-physical-session")
            result.update(
                {
                    "session_report": session["path"],
                    "gate": status.gate,
                    "expensive_reconstruction_rerun": False,
                    "fitter_rerun": False,
                    "rationale": "Continue the scoped completed physical session before spending rig time on a new reconstruction.",
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
            rejected_interrupted.append(
                {"job_id": row["job_id"], "reason": "read-only interrupted recovery assessment unavailable"}
            )
            continue
        if assessment.get("available") is True and assessment.get("expensive_reconstruction_rerun") is False:
            result = result_base(priority=4, path="interrupted-body-recovery")
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
    result = result_base(priority=5, path="fresh-profiled-physical-preflight")
    result.update(
        {
            "expensive_reconstruction_rerun": True,
            "fitter_rerun": True,
            "rejected_gate_a_resume_count": len(rejected_resume),
            "rejected_acceptance_count": len(rejected_acceptance),
            "rejected_interrupted_recovery_count": len(rejected_interrupted),
            "rationale": "No reusable scoped Gate-A rescue, downstream acceptance, completed physical session or interrupted reconstruction/package recovery validated. Only now spend rig time on fresh profiled physical preflight/reconstruction.",
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
    scope = plan.get("scope")
    if isinstance(scope, dict):
        scope_bits = [
            f"Person={scope.get('person_id') or '-'}",
            f"Performer={scope.get('performer_id') or '-'}",
            f"Body={scope.get('body_id') or '-'}",
        ]
        lines.append("Scope: " + " | ".join(scope_bits))
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
    if args.preferred_job_id and not JOB_ID.fullmatch(args.preferred_job_id):
        print("BodyRig rig-window plan: ERROR | preferred job id is invalid.", file=sys.stderr)
        return 2
    if args.person_id and not PERSON_ID.fullmatch(args.person_id):
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
