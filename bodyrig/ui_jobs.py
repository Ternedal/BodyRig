from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .bodyprint_adjustment import (
    BodyprintAdjustmentEvidenceError,
    build_adjustment_request,
)
from .package import install_package
from .person_profiles import add_body_revision, load_profile
from .storage import body_library, person_library, ui_jobs_dir

FORMAT = "bodyrig-ui-job"
VERSION = 1
_FINAL = {"succeeded", "failed", "canceled", "interrupted"}
_ADJUSTMENT_ENV = "BODYRIG_BODYPRINT_ADJUSTMENT_REQUEST"


class UiJobError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _job_path(job_id: str) -> Path:
    return ui_jobs_dir() / job_id / "job.json"


def _write_job(job: dict[str, Any]) -> None:
    path = _job_path(job["job_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temp.write_text(json.dumps(job, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _write_create_only_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise UiJobError(f"refusing to overwrite UI build input: {path}")
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")


def _read_job(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UiJobError(f"invalid UI job state: {path}") from exc
    if not isinstance(value, dict) or value.get("format") != FORMAT or value.get("version") != VERSION:
        raise UiJobError(f"unsupported UI job state: {path}")
    return value


def _powershell() -> str:
    command = shutil.which("pwsh")
    if not command:
        raise UiJobError("PowerShell 7+ executable (pwsh) was not found")
    return command


def operator_checkout_status() -> dict[str, Any]:
    root = _repo_root()
    required = [
        root / "clone-body-from-stash-ready.ps1",
        root / "accept-physical-clone.ps1",
        root / "bodyrig" / "__init__.py",
    ]
    if any(not path.is_file() for path in required):
        return {"ok": False, "reason": "BodyRig is not running from a complete operator checkout"}
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip().lower()
        dirty = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "reason": f"Could not prove BodyRig Git checkout authority: {exc}"}
    if len(head) != 40 or any(ch not in "0123456789abcdef" for ch in head):
        return {"ok": False, "reason": "BodyRig Git HEAD is invalid"}
    if dirty:
        return {"ok": False, "reason": "BodyRig operator checkout is dirty", "revision": head}
    if os.name != "nt":
        return {"ok": False, "reason": "Physical body builds are Windows-only in BodyRig V1", "revision": head}
    try:
        pwsh = _powershell()
        major_raw = subprocess.run(
            [pwsh, "-NoProfile", "-Command", "$PSVersionTable.PSVersion.Major"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (UiJobError, OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "reason": f"Could not prove PowerShell 7+ authority: {exc}", "revision": head}
    if not major_raw.isdigit() or int(major_raw) < 7:
        return {
            "ok": False,
            "reason": f"Physical body builds require PowerShell 7+ (pwsh); detected major version {major_raw!r}",
            "revision": head,
        }
    return {
        "ok": True,
        "revision": head,
        "root": str(root),
        "powershell": pwsh,
        "powershell_major": int(major_raw),
    }


class UiJobManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._reconcile_interrupted()

    def _reconcile_interrupted(self) -> None:
        root = ui_jobs_dir()
        if not root.exists():
            return
        for path in root.glob("*/job.json"):
            try:
                job = _read_job(path)
            except UiJobError:
                continue
            if job.get("status") in {"queued", "running"}:
                job["status"] = "interrupted"
                job["completed_utc"] = _now()
                job["error"] = "BodyRig service restarted before the UI job reached a terminal state. Inspect physical evidence before retrying."
                _write_job(job)

    def get(self, job_id: str) -> dict[str, Any]:
        path = _job_path(job_id)
        if not path.is_file():
            raise UiJobError("UI job not found")
        return _read_job(path)

    def list(self, *, person_id: str | None = None) -> list[dict[str, Any]]:
        root = ui_jobs_dir()
        if not root.exists():
            return []
        jobs: list[dict[str, Any]] = []
        for path in root.glob("*/job.json"):
            try:
                job = _read_job(path)
            except UiJobError:
                continue
            if person_id is None or job.get("person_id") == person_id:
                jobs.append(job)
        return sorted(jobs, key=lambda item: str(item.get("created_utc", "")), reverse=True)

    def start_body_build(
        self,
        person_id: str,
        *,
        feedback: str = "",
        changes: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        profile = load_profile(person_library(), person_id)
        source = profile.get("source")
        if not source or source.get("kind") != "stash-performer":
            raise UiJobError("Person must be bound to a Stash performer before body build")
        authority = operator_checkout_status()
        if not authority.get("ok"):
            raise UiJobError(str(authority.get("reason") or "BodyRig operator checkout is not authoritative"))
        if not os.environ.get("STASH_URL", "").strip():
            raise UiJobError("STASH_URL is not configured in the BodyRig service environment")
        if not os.environ.get("STASH_API_KEY", "").strip():
            raise UiJobError("STASH_API_KEY is not configured in the BodyRig service environment")

        adjustment_request: dict[str, Any] | None = None
        normalized_feedback = str(feedback or "").strip()
        if normalized_feedback or changes:
            if not normalized_feedback:
                raise UiJobError("Body adjustment changes require the operator feedback they were reviewed from")
            if not changes:
                raise UiJobError("Body adjustment feedback requires the exact reviewed proposal changes")
            try:
                adjustment_request = build_adjustment_request(
                    normalized_feedback,
                    changes=changes,
                )
            except BodyprintAdjustmentEvidenceError as exc:
                raise UiJobError(str(exc)) from exc

        with self._lock:
            active = [job for job in self.list(person_id=person_id) if job.get("status") in {"queued", "running"}]
            if active:
                raise UiJobError("A body build is already running for this person")
            job_id = f"job-{uuid.uuid4().hex}"
            job_root = ui_jobs_dir() / job_id
            adjustment_path: Path | None = None
            if adjustment_request is not None:
                adjustment_path = job_root / "bodyprint-adjustment-request.json"
                _write_create_only_json(adjustment_path, adjustment_request)
            job = {
                "format": FORMAT,
                "version": VERSION,
                "job_id": job_id,
                "kind": "body-build",
                "person_id": person_id,
                "status": "queued",
                "created_utc": _now(),
                "started_utc": None,
                "completed_utc": None,
                "bodyrig_revision": authority["revision"],
                "pid": None,
                "session_report": str(job_root / "physical-session.json"),
                "clone_output": str(job_root / "clone-output"),
                "acceptance_dir": str(job_root / "acceptance"),
                "log_path": str(job_root / "job.log"),
                "adjustment_request": str(adjustment_path) if adjustment_path is not None else None,
                "adjustment_feedback_sha256": adjustment_request["feedback_sha256"] if adjustment_request else None,
                "body_feedback": normalized_feedback if adjustment_request else "",
                "body_revision": None,
                "canonical_body_id": None,
                "error": None,
            }
            _write_job(job)
            thread = threading.Thread(target=self._run_body_build, args=(job_id,), name=f"bodyrig-{job_id}", daemon=True)
            thread.start()
            return job

    def _run_command(self, job: dict[str, Any], args: list[str]) -> int:
        log_path = Path(job["log_path"])
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8", newline="\n") as log:
            log.write(f"\n[{_now()}] RUN {' '.join(args[:4])} ...\n")
            child_env = os.environ.copy()
            adjustment_request = str(job.get("adjustment_request") or "").strip()
            if adjustment_request:
                child_env[_ADJUSTMENT_ENV] = adjustment_request
            else:
                child_env.pop(_ADJUSTMENT_ENV, None)
            with self._lock:
                current = self.get(job["job_id"])
                if current.get("status") != "running":
                    raise UiJobError(
                        f"UI job is no longer running; refusing subprocess start from state {current.get('status')!r}"
                    )
                authority = operator_checkout_status()
                if not authority.get("ok"):
                    raise UiJobError(
                        str(authority.get("reason") or "BodyRig operator checkout is no longer authoritative")
                    )
                expected_revision = str(current.get("bodyrig_revision") or "").strip().lower()
                actual_revision = str(authority.get("revision") or "").strip().lower()
                if actual_revision != expected_revision:
                    raise UiJobError(
                        "BodyRig checkout revision changed after UI job enqueue; "
                        f"expected {expected_revision}, got {actual_revision}. Refusing physical subprocess start."
                    )
                process = subprocess.Popen(
                    args,
                    cwd=str(_repo_root()),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=child_env,
                )
                self._processes[job["job_id"]] = process
                current["pid"] = process.pid
                _write_job(current)
                job["pid"] = process.pid
            try:
                return process.wait()
            finally:
                with self._lock:
                    self._processes.pop(job["job_id"], None)

    def _run_body_build(self, job_id: str) -> None:
        try:
            with self._lock:
                job = self.get(job_id)
                if job.get("status") != "queued":
                    return
                job["status"] = "running"
                job["started_utc"] = _now()
                _write_job(job)

            profile = load_profile(person_library(), job["person_id"])
            source = profile["source"]
            ps = _powershell()
            root = _repo_root()
            clone_args = [
                ps,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "clone-body-from-stash-ready.ps1"),
                "-PerformerId",
                str(source["performer_id"]),
                "-BodyId",
                job["person_id"],
                "-Name",
                profile["display_name"],
                "-BodyRigPython",
                sys.executable,
                "-SessionReport",
                job["session_report"],
                "-OutputDir",
                job["clone_output"],
            ]
            code = self._run_command(job, clone_args)
            if code != 0:
                raise UiJobError(f"physical Stash clone failed with exit code {code}")

            accept_args = [
                ps,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "accept-physical-clone.ps1"),
                "-SessionReport",
                job["session_report"],
                "-BodyRigPython",
                sys.executable,
                "-OutputDir",
                job["acceptance_dir"],
            ]
            code = self._run_command(job, accept_args)
            if code != 0:
                raise UiJobError(f"high-fidelity Gate A failed with exit code {code}")

            acceptance_path = Path(job["acceptance_dir"]) / "bodyrig-acceptance.json"
            acceptance = json.loads(acceptance_path.read_text(encoding="utf-8-sig"))
            package_info = acceptance.get("package") or {}
            body_id = str(package_info.get("body_id") or "")
            expected_hash = str(package_info.get("package_sha256") or "")
            package_path = Path(job["acceptance_dir"]) / f"{body_id}.mrbody"
            if not body_id or not package_path.is_file():
                raise UiJobError("Gate A passed without a canonical .mrbody package")

            with self._lock:
                current = self.get(job_id)
                if current.get("status") != "running":
                    return
                installed = install_package(package_path, body_library())
                feedback_note = str(current.get("body_feedback") or "").strip()
                if not feedback_note:
                    feedback_note = "Source-derived Stash/SiTH build via BodyRig UI"
                updated = add_body_revision(
                    person_library(),
                    current["person_id"],
                    body_id=body_id,
                    package_sha256=expected_hash,
                    package_path=str(installed),
                    preview_path=None,
                    feedback=feedback_note,
                )
                current["body_revision"] = updated["body_revisions"][-1]["revision_id"]
                current["canonical_body_id"] = body_id
                current["status"] = "succeeded"
                current["completed_utc"] = _now()
                current["pid"] = None
                _write_job(current)
        except Exception as exc:
            with self._lock:
                job = self.get(job_id)
                if job.get("status") not in _FINAL:
                    job["status"] = "failed"
                    job["completed_utc"] = _now()
                    job["pid"] = None
                    job["error"] = str(exc)[:4000]
                    _write_job(job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = self.get(job_id)
            if job.get("status") in _FINAL:
                return job
            if job.get("status") == "running":
                raise UiJobError(
                    "Running physical body builds cannot be safely canceled because WSL/child-process termination cannot be proven. "
                    "Let the active command reach a terminal state, then inspect the persisted session/evidence before retrying."
                )
            if job.get("status") != "queued":
                raise UiJobError(f"UI job cannot be canceled from state {job.get('status')!r}")
            job["status"] = "canceled"
            job["completed_utc"] = _now()
            job["pid"] = None
            job["error"] = "Canceled by operator before physical subprocess start"
            _write_job(job)
            return job


manager = UiJobManager()
