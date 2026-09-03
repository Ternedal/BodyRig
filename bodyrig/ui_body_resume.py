from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException

from .interrupted_fit_recovery import InterruptedFitRecoveryError, build_recovery_plan
from .package import install_package
from .person_body_review import PersonBodyReviewError, persist_review, validate_fidelity_output
from .person_profiles import PersonProfileError, add_body_revision, load_profile
from .person_source_alignment import PersonSourceAlignmentError, file_sha256, write_binding as write_source_binding
from .storage import body_library, person_library, ui_jobs_dir
from .ui_jobs import (
    FORMAT,
    VERSION,
    UiJobError,
    _FINAL,
    _OPEN,
    _body_source_evidence,
    _job_path,
    _now,
    _powershell,
    _read_job,
    _write_job,
    manager as ui_jobs,
    operator_checkout_status,
)

router = APIRouter()
_WORKSPACE_MARKER = "Private identity workspace: "


def _marker_value(line: str) -> str | None:
    index = line.find(_WORKSPACE_MARKER)
    if index < 0:
        return None
    value = line[index + len(_WORKSPACE_MARKER) :].strip()
    return value or None


def _identity_workspace_from_log(job: dict[str, Any]) -> Path:
    log_text = str(job.get("log_path") or "").strip()
    if not log_text:
        raise UiJobError("failed body job has no persisted log path")
    log_path = Path(log_text).expanduser().resolve()
    if not log_path.is_file():
        raise UiJobError("failed body job log is missing; retained identity workspace cannot be proven")

    marker: str | None = None
    try:
        with log_path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                value = _marker_value(line)
                if value:
                    marker = value
    except OSError as exc:
        raise UiJobError("failed body job log could not be read for recovery") from exc
    if marker is None:
        raise UiJobError("failed body job did not record a private identity workspace")

    candidate = Path(marker).expanduser()
    if not candidate.is_absolute():
        raise UiJobError("recorded private identity workspace is not an absolute path")
    candidate = candidate.resolve()
    if not candidate.is_dir():
        raise UiJobError("recorded private identity workspace is no longer present")

    body_alias = str(job.get("person_id") or "").strip()
    if not body_alias or not candidate.name.startswith(f"{body_alias}-"):
        raise UiJobError("recorded private identity workspace does not belong to this body job")

    allowed_roots: list[Path] = []
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        allowed_roots.append((Path(local_app_data).expanduser().resolve() / "BodyRig" / "identity-workspaces").resolve())
    allowed_roots.append((Path(tempfile.gettempdir()).expanduser().resolve() / "BodyRig" / "identity-workspaces").resolve())
    if not any(candidate.parent == root for root in allowed_roots):
        raise UiJobError("recorded private identity workspace is outside BodyRig's managed recovery roots")
    return candidate


def _active_jobs_for_person(person_id: str, *, ignore_job_id: str = "") -> list[dict[str, Any]]:
    return [
        job
        for job in ui_jobs.list(person_id=person_id)
        if job.get("job_id") != ignore_job_id and job.get("status") in _OPEN
    ]


def _validated_resume_source(job_id: str) -> tuple[dict[str, Any], dict[str, Any], Path, dict[str, Any]]:
    source = _read_job(_job_path(job_id))
    if source.get("kind") != "body-build":
        raise UiJobError("only a persisted body-build job can be resumed")
    if source.get("status") not in {"failed", "interrupted"}:
        raise UiJobError("body-build must be failed or interrupted before late-fit recovery")

    person_id = str(source.get("person_id") or "").strip()
    if not person_id:
        raise UiJobError("failed body-build has no person binding")
    if _active_jobs_for_person(person_id, ignore_job_id=job_id):
        raise UiJobError("another BodyRig UI build is already open for this person")

    authority = operator_checkout_status()
    if not authority.get("ok"):
        raise UiJobError(str(authority.get("reason") or "BodyRig operator checkout is not authoritative"))
    current_revision = str(authority.get("revision") or "").strip().lower()
    failed_revision = str(source.get("bodyrig_revision") or "").strip().lower()
    if failed_revision != current_revision:
        raise UiJobError(
            "late-fit recovery requires the exact BodyRig revision that produced the failed physical session; "
            f"failed={failed_revision or 'missing'}, current={current_revision or 'missing'}"
        )
    if not os.environ.get("STASH_URL", "").strip():
        raise UiJobError("STASH_URL is not configured in the BodyRig service environment")
    if not os.environ.get("STASH_API_KEY", "").strip():
        raise UiJobError("STASH_API_KEY is not configured in the BodyRig service environment")

    workspace = _identity_workspace_from_log(source)
    try:
        plan = build_recovery_plan(
            failed_session_path=str(source.get("session_report") or ""),
            stash_clone_output=str(source.get("clone_output") or ""),
            identity_workspace=workspace,
            current_revision=current_revision,
        )
    except (InterruptedFitRecoveryError, OSError, ValueError) as exc:
        raise UiJobError(str(exc)) from exc
    if plan.get("package_already_complete") is True:
        raise UiJobError("failed clone already contains a complete package; late-fit recovery refuses to overwrite it")

    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise UiJobError(str(exc)) from exc
    profile_source = profile.get("source")
    if not isinstance(profile_source, dict) or profile_source.get("kind") != "stash-performer":
        raise UiJobError("person is no longer bound to a Stash performer")
    if str(profile_source.get("performer_id") or "") != str(plan.get("performer_id") or ""):
        raise UiJobError("person's current Stash performer differs from the failed physical session")
    return source, plan, workspace, profile


def inspect_body_resume(job_id: str) -> dict[str, Any]:
    try:
        source, plan, _workspace, _profile = _validated_resume_source(job_id)
    except (UiJobError, OSError, ValueError) as exc:
        return {"available": False, "source_job_id": job_id, "reason": str(exc)}
    return {
        "available": True,
        "source_job_id": job_id,
        "person_id": source["person_id"],
        "bodyrig_revision": plan["bodyrig_revision"],
        "failed_session_id": plan["failed_session_id"],
        "reconstruction_sha256": plan["authority"]["reconstruction_sha256"],
        "expensive_reconstruction_rerun": False,
        "reason": "Completed SiTH reconstruction is intact and exact-authority late-fit recovery is available.",
    }


def start_body_resume(job_id: str) -> dict[str, Any]:
    source, plan, workspace, profile = _validated_resume_source(job_id)
    person_id = str(source["person_id"])
    with ui_jobs._lock:
        current_source = _read_job(_job_path(job_id))
        if current_source.get("status") not in {"failed", "interrupted"}:
            raise UiJobError("source body-build changed state while recovery was being prepared")
        if str(current_source.get("bodyrig_revision") or "").lower() != str(plan["bodyrig_revision"]).lower():
            raise UiJobError("source body-build authority changed while recovery was being prepared")
        if _active_jobs_for_person(person_id, ignore_job_id=job_id):
            raise UiJobError("another BodyRig UI build opened while late-fit recovery was being prepared")

        new_job_id = f"job-{uuid.uuid4().hex}"
        root = ui_jobs_dir() / new_job_id
        job = {
            "format": FORMAT,
            "version": VERSION,
            "job_id": new_job_id,
            "kind": "body-build",
            "person_id": person_id,
            "status": "queued",
            "created_utc": _now(),
            "started_utc": None,
            "completed_utc": None,
            "bodyrig_revision": plan["bodyrig_revision"],
            "pid": None,
            "session_report": str(root / "physical-session-recovered.json"),
            "clone_output": str(source["clone_output"]),
            "acceptance_dir": str(root / "acceptance"),
            "fidelity_dir": str(root / "fidelity-review"),
            "log_path": str(root / "job.log"),
            "adjustment_request": None,
            "adjustment_feedback_sha256": source.get("adjustment_feedback_sha256"),
            "body_feedback": str(source.get("body_feedback") or ""),
            "body_revision": None,
            "canonical_body_id": None,
            "source_binding_sha256": None,
            "body_review_sha256": None,
            "error": None,
            "resume_mode": "interrupted-fit",
            "resume_of_job_id": job_id,
            "resume_reconstruction_sha256": plan["authority"]["reconstruction_sha256"],
            "recovery_receipt": str(root / "interrupted-fit-recovery.json"),
        }
        _write_job(job)
        thread = threading.Thread(
            target=_run_body_resume,
            args=(new_job_id, job_id, str(workspace)),
            name=f"bodyrig-resume-{new_job_id}",
            daemon=True,
        )
        thread.start()
        return job


def _run_body_resume(job_id: str, source_job_id: str, workspace_text: str) -> None:
    try:
        with ui_jobs._lock:
            job = _read_job(_job_path(job_id))
            if job.get("status") != "queued":
                return
            job["status"] = "running"
            job["started_utc"] = _now()
            _write_job(job)

        source, plan, workspace, profile = _validated_resume_source(source_job_id)
        if workspace != Path(workspace_text).resolve():
            raise UiJobError("retained identity workspace changed between recovery enqueue and execution")
        if str(plan["authority"]["reconstruction_sha256"]) != str(job.get("resume_reconstruction_sha256") or ""):
            raise UiJobError("SiTH reconstruction authority changed between recovery enqueue and execution")

        log_path = Path(job["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as log:
            log.write(f"[{_now()}] BodyRig late-fit resume from {source_job_id}\n")
            log.write(f"Private identity workspace: {workspace}\n")
            log.write(f"Reconstruction SHA-256: {plan['authority']['reconstruction_sha256']}\n")
            log.write("Resume policy: completed reconstruction reused unchanged; PHALP/4D-Humans recovery is not rerun.\n")

        ps = _powershell()
        repo_root = Path(__file__).resolve().parents[1]
        resume_args = [
            ps,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "resume-interrupted-physical-fit.ps1"),
            "-FailedSessionReport",
            str(source["session_report"]),
            "-CloneOutput",
            str(source["clone_output"]),
            "-IdentityWorkspace",
            str(workspace),
            "-BodyRigPython",
            sys.executable,
            "-RecoveredSessionReport",
            str(job["session_report"]),
            "-RecoveryReceipt",
            str(job["recovery_receipt"]),
        ]
        code = ui_jobs._run_command(job, resume_args)
        if code != 0:
            raise UiJobError(f"interrupted physical fit recovery failed with exit code {code}")
        recovery_receipt_path = Path(job["recovery_receipt"])
        if not recovery_receipt_path.is_file():
            raise UiJobError("late-fit recovery returned success without its create-only recovery receipt")

        accept_args = [
            ps,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "accept-physical-clone.ps1"),
            "-SessionReport",
            str(job["session_report"]),
            "-BodyRigPython",
            sys.executable,
            "-OutputDir",
            str(job["acceptance_dir"]),
        ]
        code = ui_jobs._run_command(job, accept_args)
        if code != 0:
            raise UiJobError(f"high-fidelity Gate A failed after late-fit recovery with exit code {code}")

        acceptance_path = Path(job["acceptance_dir"]) / "bodyrig-acceptance.json"
        acceptance = json.loads(acceptance_path.read_text(encoding="utf-8-sig"))
        package_info = acceptance.get("package") or {}
        body_id = str(package_info.get("body_id") or "")
        expected_hash = str(package_info.get("package_sha256") or "")
        package_path = Path(job["acceptance_dir"]) / f"{body_id}.mrbody"
        if not body_id or not package_path.is_file():
            raise UiJobError("Gate A passed after late-fit recovery without a canonical .mrbody package")

        fidelity_args = [
            ps,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo_root / "run-fidelity-windows-render-probe.ps1"),
            "-AcceptanceDir",
            str(job["acceptance_dir"]),
            "-OutputDir",
            str(job["fidelity_dir"]),
            "-BodyRigPython",
            sys.executable,
        ]
        code = ui_jobs._run_command(job, fidelity_args)
        if code != 0:
            raise UiJobError(f"fidelity reference-render review capture failed after late-fit recovery with exit code {code}")
        try:
            validate_fidelity_output(job["fidelity_dir"], body_id=body_id, package_sha256=expected_hash)
            review = persist_review(
                person_library(),
                person_id=str(job["person_id"]),
                fidelity_output_dir=str(job["fidelity_dir"]),
                body_id=body_id,
                package_sha256=expected_hash,
            )
        except PersonBodyReviewError as exc:
            raise UiJobError(f"recovered fidelity review evidence is not authoritative: {exc}") from exc
        review_receipt_sha = file_sha256(Path(review["root"]) / "review.json")

        current_profile = load_profile(person_library(), str(job["person_id"]))
        current_source = current_profile.get("source")
        if not isinstance(current_source, dict) or str(current_source.get("performer_id") or "") != str(plan["performer_id"]):
            raise UiJobError("person's Stash source changed before recovered body registration")
        manifest_path, source_files = _body_source_evidence(
            str(source["clone_output"]),
            performer_id=str(plan["performer_id"]),
        )
        manifest_sha = file_sha256(manifest_path)

        with ui_jobs._lock:
            current = _read_job(_job_path(job_id))
            if current.get("status") != "running":
                return
            installed = install_package(package_path, body_library(), expected_sha256=expected_hash)
            feedback_note = str(current.get("body_feedback") or "").strip()
            if not feedback_note:
                feedback_note = f"Recovered interrupted source-derived Stash/SiTH fit from UI job {source_job_id}"
            updated = add_body_revision(
                person_library(),
                str(current["person_id"]),
                body_id=body_id,
                package_sha256=expected_hash,
                package_path=str(installed),
                preview_path=None,
                feedback=feedback_note,
            )
            body_revision = str(updated["body_revisions"][-1]["revision_id"])
            try:
                write_source_binding(
                    person_library(),
                    updated,
                    kind="body",
                    revision_id=body_revision,
                    evidence_kind="stash-physical-source-manifest-v1",
                    evidence_sha256=manifest_sha,
                    evidence_ref=str(manifest_path),
                    source_files=source_files,
                )
            except PersonSourceAlignmentError as exc:
                raise UiJobError(f"recovered body candidate could not be bound to exact Stash source evidence: {exc}") from exc
            current["body_revision"] = body_revision
            current["canonical_body_id"] = body_id
            current["source_binding_sha256"] = file_sha256(
                person_library() / ".source-bindings" / str(current["person_id"]) / f"{body_revision}.json"
            )
            current["body_review_sha256"] = review_receipt_sha
            current["recovery_receipt_sha256"] = file_sha256(recovery_receipt_path)
            current["status"] = "succeeded"
            current["completed_utc"] = _now()
            current["pid"] = None
            current["error"] = None
            _write_job(current)
    except Exception as exc:
        with ui_jobs._lock:
            try:
                job = _read_job(_job_path(job_id))
            except UiJobError:
                return
            if job.get("status") not in _FINAL:
                job["status"] = "failed"
                job["completed_utc"] = _now()
                job["pid"] = None
                job["error"] = str(exc)[:4000]
                _write_job(job)


@router.get("/api/v1/jobs/{job_id}/resume-status")
def body_resume_status(job_id: str) -> dict[str, Any]:
    return inspect_body_resume(job_id)


@router.post("/api/v1/jobs/{job_id}/resume")
def body_resume(job_id: str) -> dict[str, Any]:
    try:
        return start_body_resume(job_id)
    except UiJobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
