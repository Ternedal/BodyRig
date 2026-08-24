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

from .package import install_package
from .person_profiles import add_body_revision, load_profile
from .storage import body_library, person_library, ui_jobs_dir

FORMAT = "bodyrig-ui-job"
VERSION = 1
_FINAL = {"succeeded", "failed", "canceled", "interrupted"}


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


def _read_job(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UiJobError(f"invalid UI job state: {path}") from exc
    if not isinstance(value, dict) or value.get("format") != FORMAT or value.get("version") != VERSION:
        raise UiJobError(f"unsupported UI job state: {path}")
    return value


def _powershell() -> str:
    command = shutil.which("pwsh") or shutil.which("powershell")
    if not command:
        raise UiJobError("PowerShell was not found")
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
    return {"ok": True, "revision": head, "root": str(root)}


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

    def start_body_build(self, person_id: str) -> dict[str, Any]:
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

        with self._lock:
            active = [job for job in self.list(person_id=person_id) if job.get("status") in {"queued", "running"}]
            if active:
                raise UiJobError("A body build is already running for this person")
            job_id = f"job-{uuid.uuid4().hex}"
            job_root = ui_jobs_dir() / job_id
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
            process = subprocess.Popen(
                args,
                cwd=str(_repo_root()),
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
                env=os.environ.copy(),
            )
            with self._lock:
                self._processes[job["job_id"]] = process
                job["pid"] = process.pid
                _write_job(job)
            try:
                return process.wait()
            finally:
                with self._lock:
                    self._processes.pop(job["job_id"], None)

    def _run_body_build(self, job_id: str) -> None:
        job = self.get(job_id)
        try:
            profile = load_profile(person_library(), job["person_id"])
            source = profile["source"]
            job["status"] = "running"
            job["started_utc"] = _now()
            _write_job(job)

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

            installed = install_package(package_path, body_library())
            updated = add_body_revision(
                person_library(),
                job["person_id"],
                body_id=body_id,
                package_sha256=expected_hash,
                package_path=str(installed),
                preview_path=None,
                feedback="Source-derived Stash/SiTH build via BodyRig UI",
                activate=True,
            )
            job["body_revision"] = updated["active"]["body_revision"]
            job["canonical_body_id"] = body_id
            job["status"] = "succeeded"
            job["completed_utc"] = _now()
            job["pid"] = None
            _write_job(job)
        except Exception as exc:  # job boundary: persist failure for UI rather than lose it with thread
            job = self.get(job_id)
            if job.get("status") != "canceled":
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
            process = self._processes.get(job_id)
            if process is not None and process.poll() is None:
                process.terminate()
            job["status"] = "canceled"
            job["completed_utc"] = _now()
            job["pid"] = None
            job["error"] = "Canceled by operator"
            _write_job(job)
            return job


manager = UiJobManager()
