from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .gate_a_resume import resume_gate_a
from .package import install_package
from .person_body_review import persist_review, validate_fidelity_output
from .person_profiles import add_body_revision, load_profile
from .person_source_alignment import file_sha256, write_binding as write_source_binding
from .storage import body_library, person_library
from .ui_jobs import (
    _body_source_evidence,
    _job_path,
    _now,
    _powershell,
    _read_job,
    _repo_root,
    _write_job,
    operator_checkout_status,
)


class ResumeBodyJobError(RuntimeError):
    pass


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResumeBodyJobError(f"{label} is unreadable: {path}") from exc
    if not isinstance(value, dict):
        raise ResumeBodyJobError(f"{label} must be a JSON object: {path}")
    return value


def _quarantine_partial(path: Path, *, label: str) -> Path | None:
    if not path.exists():
        return None
    target = path.with_name(f"{path.name}.failed-{_stamp()}")
    if target.exists():
        raise ResumeBodyJobError(f"{label} quarantine target already exists: {target}")
    os.replace(path, target)
    return target


def _acquire_resume_claim(job_id: str) -> Path:
    """Atomically claim one persisted job for a mutating Gate-A rescue."""

    job_path = _job_path(job_id)
    if not job_path.is_file():
        raise ResumeBodyJobError(f"BodyRig body job not found: {job_id}")
    claim_path = job_path.parent / ".gate-a-resume.lock"
    payload = json.dumps(
        {
            "format": "bodyrig-gate-a-resume-lock",
            "version": 1,
            "job_id": job_id,
            "pid": os.getpid(),
            "started_utc": _now(),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ) + "\n"
    try:
        descriptor = os.open(claim_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError as exc:
        raise ResumeBodyJobError(
            f"Gate A resume is already claimed for {job_id}; refusing concurrent rescue"
        ) from exc
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
            handle.flush()
    except Exception:
        claim_path.unlink(missing_ok=True)
        raise
    return claim_path


def _release_resume_claim(claim_path: Path) -> None:
    try:
        claim_path.unlink(missing_ok=True)
    except OSError as exc:
        raise ResumeBodyJobError(f"could not release Gate A resume claim: {claim_path}") from exc


def _run_logged(job: dict[str, Any], command: list[str]) -> int:
    log_path = Path(str(job["log_path"])).expanduser().resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8", newline="\n") as log:
        log.write(f"\n[{_now()}] RESUME RUN {' '.join(command[:5])} ...\n")
        log.flush()
        completed = subprocess.run(
            command,
            cwd=str(_repo_root()),
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        return completed.returncode


def _existing_body_revision(profile: dict[str, Any], *, body_id: str, package_sha256: str) -> str | None:
    for item in profile.get("body_revisions", []):
        if not isinstance(item, dict):
            continue
        if item.get("body_id") == body_id and item.get("package_sha256") == package_sha256:
            revision = str(item.get("revision_id") or "")
            if revision:
                return revision
    return None


def _resume_context(job_id: str) -> dict[str, Any]:
    path = _job_path(job_id)
    job = _read_job(path)
    if job.get("kind") != "body-build":
        raise ResumeBodyJobError("only a physical body-build job can be resumed")
    if job.get("status") != "failed":
        raise ResumeBodyJobError(f"body job must be failed before Gate A resume, got {job.get('status')!r}")
    error = str(job.get("error") or "")
    source_error = str(job.get("resume_source_error") or "")
    if "high-fidelity Gate A failed" not in error and "high-fidelity Gate A failed" not in source_error:
        raise ResumeBodyJobError("body job did not fail at high-fidelity Gate A; refusing cross-stage resume")

    authority = operator_checkout_status()
    if not authority.get("ok"):
        raise ResumeBodyJobError(str(authority.get("reason") or "BodyRig checkout is not authoritative"))
    validator_revision = str(authority["revision"])
    producer_revision = str(job.get("bodyrig_revision") or "").strip().lower()
    if len(producer_revision) != 40:
        raise ResumeBodyJobError("failed job has no canonical producer revision")
    if producer_revision == validator_revision:
        raise ResumeBodyJobError("Gate A resume requires a newer validator revision than the failed producer job")

    return {
        "path": path,
        "job": job,
        "producer_revision": producer_revision,
        "validator_revision": validator_revision,
        "acceptance_dir": Path(str(job["acceptance_dir"])).expanduser().resolve(),
        "fidelity_dir": Path(str(job["fidelity_dir"])).expanduser().resolve(),
        "session_report": Path(str(job["session_report"])).expanduser().resolve(),
    }


def assess_body_job_resume(job_id: str) -> dict[str, Any]:
    """Prove that a failed Gate-A body job can be resumed without persistent mutation.

    The canonical Gate-A implementation is executed against a temporary output
    directory so the assessment exercises the same immutable producer evidence,
    package lineage, skin/topology QA and runtime materialization as the real
    resume. The temporary result is removed before this function returns.
    """

    context = _resume_context(job_id)
    with tempfile.TemporaryDirectory(prefix="bodyrig-gate-a-resume-assessment-") as temp_root:
        gate = resume_gate_a(
            session_report=context["session_report"],
            validator_revision=context["validator_revision"],
            output_dir=Path(temp_root) / "acceptance",
            python_executable=sys.executable,
        )

    return {
        "format": "bodyrig-body-job-resume-assessment",
        "version": 1,
        "job_id": job_id,
        "eligible": True,
        "persistent_mutation": False,
        "producer_revision": context["producer_revision"],
        "validator_revision": context["validator_revision"],
        "body_id": gate["body_id"],
        "package_sha256": gate["package_sha256"],
        "skin_assessment": gate["skin_assessment"],
        "topology_assessment": gate["topology_assessment"],
        "recovery_rerun": False,
        "fitter_rerun": False,
        "next_gate": "historical-gate-a-resume",
    }


def resume_body_job(job_id: str) -> dict[str, Any]:
    claim_path = _acquire_resume_claim(job_id)
    context: dict[str, Any] | None = None
    staged_acceptance: Path | None = None
    quarantined_acceptance: Path | None = None
    quarantined_fidelity: Path | None = None
    promoted = False
    owner_pid = os.getpid()
    try:
        # Re-read and validate under the exclusive claim so a second rescue or
        # UI recovery cannot race the transition from failed -> running.
        context = _resume_context(job_id)
        path = context["path"]
        producer_revision = context["producer_revision"]
        validator_revision = context["validator_revision"]
        acceptance_dir = context["acceptance_dir"]
        fidelity_dir = context["fidelity_dir"]
        session_report = context["session_report"]

        current = _read_job(path)
        original_error = str(current.get("resume_source_error") or current.get("error") or "")
        current["resume_source_error"] = original_error
        current["producer_revision"] = producer_revision
        current["validator_revision"] = validator_revision
        current["status"] = "running"
        current["completed_utc"] = None
        current["pid"] = owner_pid
        current["error"] = None
        current["resume_stage"] = "gate-a-validating"
        current["resume_started_utc"] = _now()
        _write_job(current)

        # Build and fully validate the replacement Gate A beside the canonical
        # output first. Historical/partial output is not moved until immutable
        # producer evidence, package lineage, QA and runtime materialization pass.
        staged_acceptance = acceptance_dir.with_name(
            f"{acceptance_dir.name}.resume-staging-{uuid.uuid4().hex}"
        )
        gate = resume_gate_a(
            session_report=session_report,
            validator_revision=validator_revision,
            output_dir=staged_acceptance,
            python_executable=sys.executable,
        )

        body_id = str(gate["body_id"])
        expected_hash = str(gate["package_sha256"])
        staged_package = staged_acceptance / f"{body_id}.mrbody"
        if not body_id or len(expected_hash) != 64 or not staged_package.is_file():
            raise ResumeBodyJobError("staged Gate A did not produce a canonical package authority")

        current = _read_job(path)
        if current.get("status") != "running" or current.get("pid") != owner_pid:
            raise ResumeBodyJobError("Gate A resume lost persisted job ownership before promotion")
        current["resume_stage"] = "gate-a-promoting"
        _write_job(current)

        # Every committed resume derives a fresh Gate A result from immutable
        # producer evidence. Previous output is quarantined only after the full
        # replacement is ready; pre-promotion failures restore quarantined dirs.
        if acceptance_dir.exists():
            quarantined_acceptance = _quarantine_partial(acceptance_dir, label="previous Gate A")
        if fidelity_dir.exists():
            quarantined_fidelity = _quarantine_partial(fidelity_dir, label="partial fidelity review")

        if acceptance_dir.exists():
            raise ResumeBodyJobError("canonical Gate A destination unexpectedly exists after quarantine")
        os.replace(staged_acceptance, acceptance_dir)
        promoted = True

        package_path = acceptance_dir / f"{body_id}.mrbody"
        if not package_path.is_file():
            raise ResumeBodyJobError("committed resumed Gate A package is missing after atomic directory promotion")

        current = _read_job(path)
        if current.get("status") != "running" or current.get("pid") != owner_pid:
            raise ResumeBodyJobError("Gate A resume lost persisted job ownership before fidelity review")
        current["resume_stage"] = "fidelity-review"
        _write_job(current)

        ps = _powershell()
        fidelity_command = [
            ps,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(_repo_root() / "run-fidelity-windows-render-probe.ps1"),
            "-AcceptanceDir",
            str(acceptance_dir),
            "-OutputDir",
            str(fidelity_dir),
            "-BodyRigPython",
            sys.executable,
        ]
        code = _run_logged(current, fidelity_command)
        if code != 0:
            raise ResumeBodyJobError(f"fidelity reference-render review capture failed with exit code {code}")

        validate_fidelity_output(fidelity_dir, body_id=body_id, package_sha256=expected_hash)
        review = persist_review(
            person_library(),
            person_id=str(current["person_id"]),
            fidelity_output_dir=fidelity_dir,
            body_id=body_id,
            package_sha256=expected_hash,
        )
        review_receipt_sha = file_sha256(Path(review["root"]) / "review.json")

        profile = load_profile(person_library(), str(current["person_id"]))
        source = profile["source"]
        manifest_path, source_files = _body_source_evidence(
            str(current["clone_output"]),
            performer_id=str(source["performer_id"]),
        )
        manifest_sha = file_sha256(manifest_path)

        installed = install_package(package_path, body_library(), expected_sha256=expected_hash)
        profile = load_profile(person_library(), str(current["person_id"]))
        body_revision = _existing_body_revision(profile, body_id=body_id, package_sha256=expected_hash)
        if body_revision is None:
            feedback_note = str(current.get("body_feedback") or "").strip()
            if not feedback_note:
                feedback_note = "Source-derived Stash/SiTH build via BodyRig UI"
            profile = add_body_revision(
                person_library(),
                str(current["person_id"]),
                body_id=body_id,
                package_sha256=expected_hash,
                package_path=str(installed),
                preview_path=None,
                feedback=feedback_note,
            )
            body_revision = str(profile["body_revisions"][-1]["revision_id"])
        else:
            profile = load_profile(person_library(), str(current["person_id"]))

        write_source_binding(
            person_library(),
            profile,
            kind="body",
            revision_id=body_revision,
            evidence_kind="stash-physical-source-manifest-v1",
            evidence_sha256=manifest_sha,
            evidence_ref=str(manifest_path),
            source_files=source_files,
        )
        binding_path = person_library() / ".source-bindings" / str(current["person_id"]) / f"{body_revision}.json"

        finished = _read_job(path)
        if finished.get("status") != "running" or finished.get("pid") != owner_pid:
            raise ResumeBodyJobError("Gate A resume lost persisted job ownership before final registration")
        finished["body_revision"] = body_revision
        finished["canonical_body_id"] = body_id
        finished["source_binding_sha256"] = file_sha256(binding_path)
        finished["body_review_sha256"] = review_receipt_sha
        finished["status"] = "succeeded"
        finished["completed_utc"] = _now()
        finished["pid"] = None
        finished["error"] = None
        finished["resume_stage"] = "complete"
        finished["resumed_without_clone_rerun"] = True
        finished["quarantined_acceptance"] = str(quarantined_acceptance) if quarantined_acceptance else None
        finished["quarantined_fidelity"] = str(quarantined_fidelity) if quarantined_fidelity else None
        _write_job(finished)
        return finished
    except Exception as exc:
        rollback_errors: list[str] = []
        if staged_acceptance is not None and staged_acceptance.exists():
            shutil.rmtree(staged_acceptance, ignore_errors=True)
        if context is not None and not promoted:
            for quarantined, canonical, label in (
                (quarantined_acceptance, context["acceptance_dir"], "Gate A"),
                (quarantined_fidelity, context["fidelity_dir"], "fidelity"),
            ):
                if quarantined is None or not quarantined.exists() or canonical.exists():
                    continue
                try:
                    os.replace(quarantined, canonical)
                except OSError as rollback_exc:
                    rollback_errors.append(f"{label} rollback failed: {rollback_exc}")
        if context is not None:
            try:
                failed = _read_job(context["path"])
                if failed.get("status") == "running" and failed.get("pid") == owner_pid:
                    detail = str(exc)
                    if rollback_errors:
                        detail += " | " + " | ".join(rollback_errors)
                    failed["status"] = "failed"
                    failed["completed_utc"] = _now()
                    failed["pid"] = None
                    failed["error"] = detail[:4000]
                    failed["resume_stage"] = "failed"
                    failed["producer_revision"] = context["producer_revision"]
                    failed["validator_revision"] = context["validator_revision"]
                    if not str(failed.get("resume_source_error") or ""):
                        failed["resume_source_error"] = str(context["job"].get("error") or "")
                    _write_job(failed)
            except Exception:
                pass
        raise
    finally:
        _release_resume_claim(claim_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Assess or resume a BodyRig UI body job that failed only at Gate A without rerunning clone/recovery/fitting."
    )
    parser.add_argument("job_id")
    parser.add_argument(
        "--assess-only",
        action="store_true",
        help="Run the complete Gate-A validator against temporary output and report resume eligibility without persistent mutation.",
    )
    args = parser.parse_args(argv)
    try:
        if args.assess_only:
            value = assess_body_job_resume(args.job_id)
            print(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
            return 0
        result = resume_body_job(args.job_id)
    except Exception as exc:
        print(f"BodyRig body-job Gate A resume: FAIL: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "job_id": result["job_id"],
        "status": result["status"],
        "body_revision": result.get("body_revision"),
        "canonical_body_id": result.get("canonical_body_id"),
        "producer_revision": result.get("producer_revision"),
        "validator_revision": result.get("validator_revision"),
        "resumed_without_clone_rerun": result.get("resumed_without_clone_rerun"),
    }, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
