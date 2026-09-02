from __future__ import annotations

import hashlib
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
from .person_profiles import add_body_revision, add_voice_revision, load_profile
from .person_source_alignment import (
    PersonSourceAlignmentError,
    file_sha256,
    write_binding as write_source_binding,
)
from .person_voice_source import PersonVoiceSourceError, source_files_for_body
from .storage import body_library, person_library, ui_jobs_dir
from .voicerig_client import VoiceRigClient, VoiceRigClientError, VoiceRigConfig

FORMAT = "bodyrig-ui-job"
VERSION = 1
_FINAL = {"succeeded", "failed", "canceled", "interrupted"}
_OPEN = {"uploading", "queued", "running", "needs_speaker", "needs_reference", "cancelling"}
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


def _body_source_evidence(clone_output: str, *, performer_id: str) -> tuple[Path, list[dict[str, str]]]:
    manifest_path = Path(clone_output).expanduser().resolve() / "bodyrig-stash-source-manifest.json"
    if not manifest_path.is_file():
        raise UiJobError("physical body build completed without its Stash source manifest")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UiJobError("physical body build Stash source manifest is unreadable") from exc
    if not isinstance(manifest, dict) or manifest.get("format") != "bodyrig-stash-source-manifest" or manifest.get("version") != 1:
        raise UiJobError("physical body build Stash source manifest format/version mismatch")
    performer = manifest.get("performer")
    if not isinstance(performer, dict) or str(performer.get("id") or "") != str(performer_id):
        raise UiJobError("physical body build Stash performer no longer matches the Person source")
    selected = manifest.get("selected")
    if not isinstance(selected, list) or not selected:
        raise UiJobError("physical body build Stash source manifest has no selected media")
    source_files: list[dict[str, str]] = []
    for item in selected:
        if not isinstance(item, dict):
            raise UiJobError("physical body build Stash selected-source entry is invalid")
        source_path = Path(str(item.get("path") or "")).expanduser().resolve()
        if not source_path.is_file():
            raise UiJobError(f"physical body build source file is no longer readable: {source_path.name}")
        source_files.append(
            {
                "scene_id": str(item.get("scene_id") or ""),
                "name": source_path.name,
                "sha256": file_sha256(source_path),
            }
        )
    return manifest_path, source_files


def _voicerig_client() -> VoiceRigClient:
    url = os.environ.get("VOICERIG_URL", "").strip() or "http://127.0.0.1:8765"
    return VoiceRigClient(VoiceRigConfig(url=url))


def _source_receipt_files(evidence: dict[str, Any]) -> list[dict[str, str]]:
    return [
        {"scene_id": str(item["scene_id"]), "name": str(item["name"]), "sha256": str(item["sha256"])}
        for item in evidence["source_files"]
    ]


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
            kind = job.get("kind")
            status = job.get("status")
            if kind == "body-build" and status in {"queued", "running"}:
                job["status"] = "interrupted"
                job["completed_utc"] = _now()
                job["error"] = "BodyRig service restarted before the UI job reached a terminal state. Inspect physical evidence before retrying."
                _write_job(job)
            elif kind == "voice-build" and status in _OPEN and not job.get("voicerig_job_id"):
                job["status"] = "interrupted"
                job["completed_utc"] = _now()
                job["error"] = "BodyRig restarted before VoiceRig returned a recoverable job id. No voice candidate was created."
                _write_job(job)

    def get(self, job_id: str) -> dict[str, Any]:
        path = _job_path(job_id)
        if not path.is_file():
            raise UiJobError("UI job not found")
        job = _read_job(path)
        if job.get("kind") == "voice-build" and job.get("status") not in _FINAL:
            return self._sync_voice_job(job)
        return job

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
            active = [job for job in self.list(person_id=person_id) if job.get("status") in _OPEN]
            if active:
                raise UiJobError("Another BodyRig UI build is already open for this person")
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
                "source_binding_sha256": None,
                "error": None,
            }
            _write_job(job)
            thread = threading.Thread(target=self._run_body_build, args=(job_id,), name=f"bodyrig-{job_id}", daemon=True)
            thread.start()
            return job

    def start_voice_build(self, person_id: str, *, body_revision: str, language: str = "da") -> dict[str, Any]:
        profile = load_profile(person_library(), person_id)
        if not profile.get("source"):
            raise UiJobError("Person must be bound to a Stash performer before source-derived voice build")
        clean_language = str(language or "").strip()
        if not clean_language or len(clean_language) > 32:
            raise UiJobError("Voice build language is invalid")
        try:
            evidence = source_files_for_body(person_library(), profile, body_revision=body_revision)
        except PersonVoiceSourceError as exc:
            raise UiJobError(str(exc)) from exc
        source_files = _source_receipt_files(evidence)

        with self._lock:
            active = [job for job in self.list(person_id=person_id) if job.get("status") in _OPEN]
            if active:
                raise UiJobError("Another BodyRig UI build is already open for this person")
            job_id = f"job-{uuid.uuid4().hex}"
            job = {
                "format": FORMAT,
                "version": VERSION,
                "job_id": job_id,
                "kind": "voice-build",
                "person_id": person_id,
                "status": "uploading",
                "created_utc": _now(),
                "started_utc": _now(),
                "completed_utc": None,
                "body_revision": body_revision,
                "language": clean_language,
                "source_manifest": evidence["manifest_path"],
                "source_manifest_sha256": evidence["manifest_sha256"],
                "source_files": source_files,
                "voicerig_job_id": None,
                "progress": 0,
                "stage": "uploading",
                "message": "Verifierede Stash-kilder uploades til VoiceRig…",
                "speaker_choices": None,
                "reference_choices": None,
                "voice_revision": None,
                "voice_package": None,
                "package_sha256": None,
                "source_binding_sha256": None,
                "error": None,
            }
            _write_job(job)

        try:
            client = _voicerig_client()
            client.health()
            remote = client.start_voice_job(
                name=profile["display_name"],
                language=clean_language,
                files=[Path(item["path"]) for item in evidence["source_files"]],
            )
            with self._lock:
                current = _read_job(_job_path(job_id))
                current["voicerig_job_id"] = str(remote["id"])
                self._apply_remote_voice_state(current, remote)
                _write_job(current)
                return current
        except (VoiceRigClientError, OSError, ValueError) as exc:
            with self._lock:
                current = _read_job(_job_path(job_id))
                current["status"] = "failed"
                current["completed_utc"] = _now()
                current["stage"] = "failed"
                current["message"] = "Source-derived VoiceRig build could not be started."
                current["error"] = str(exc)[:4000]
                _write_job(current)
                return current

    @staticmethod
    def _apply_remote_voice_state(job: dict[str, Any], remote: dict[str, Any]) -> None:
        state = str(remote.get("state") or "").strip()
        if state == "cancelled":
            job["status"] = "canceled"
        elif state in {"queued", "running", "needs_speaker", "needs_reference", "cancelling", "succeeded", "failed"}:
            job["status"] = state
        else:
            raise UiJobError(f"VoiceRig returned unsupported job state: {state!r}")
        progress = remote.get("progress")
        job["progress"] = int(progress) if isinstance(progress, (int, float)) and not isinstance(progress, bool) else 0
        job["stage"] = str(remote.get("stage") or "")
        job["message"] = str(remote.get("message") or "")
        job["speaker_choices"] = remote.get("speaker_choices") if isinstance(remote.get("speaker_choices"), list) else None
        job["reference_choices"] = remote.get("reference_choices") if isinstance(remote.get("reference_choices"), list) else None
        job["error"] = str(remote.get("error") or "") or None
        if job["status"] in {"failed", "canceled"}:
            job["completed_utc"] = _now()

    def _sync_voice_job(self, job: dict[str, Any]) -> dict[str, Any]:
        remote_id = str(job.get("voicerig_job_id") or "")
        if not remote_id:
            return job
        try:
            client = _voicerig_client()
            remote = client.voice_job(remote_id)
            with self._lock:
                current = _read_job(_job_path(job["job_id"]))
                if current.get("status") in _FINAL:
                    return current
                self._apply_remote_voice_state(current, remote)
                if current.get("status") == "succeeded":
                    return self._finalize_voice_build(current, remote, client)
                _write_job(current)
                return current
        except (VoiceRigClientError, UiJobError, PersonVoiceSourceError, PersonSourceAlignmentError, OSError, ValueError) as exc:
            with self._lock:
                current = _read_job(_job_path(job["job_id"]))
                current["status"] = "failed"
                current["completed_utc"] = _now()
                current["stage"] = "provenance_failed"
                current["message"] = "VoiceRig-resultatet blev ikke accepteret som source-bound voice."
                current["error"] = str(exc)[:4000]
                _write_job(current)
                return current

    def _finalize_voice_build(self, job: dict[str, Any], remote: dict[str, Any], client: VoiceRigClient) -> dict[str, Any]:
        profile = load_profile(person_library(), str(job["person_id"]))
        evidence = source_files_for_body(
            person_library(),
            profile,
            body_revision=str(job["body_revision"]),
        )
        source_files = _source_receipt_files(evidence)
        if evidence["manifest_sha256"] != job.get("source_manifest_sha256"):
            raise UiJobError("Stash source manifest changed while VoiceRig was building the voice")
        if evidence["manifest_path"] != job.get("source_manifest"):
            raise UiJobError("Stash source manifest path changed while VoiceRig was building the voice")
        if source_files != job.get("source_files"):
            raise UiJobError("Stash source file evidence changed while VoiceRig was building the voice")

        result = remote.get("result")
        if not isinstance(result, dict):
            raise UiJobError("VoiceRig succeeded without a result object")
        voice = result.get("voice")
        if not isinstance(voice, dict):
            raise UiJobError("VoiceRig succeeded without voice identity")
        voice_id = str(voice.get("id") or "").strip()
        package = str(result.get("package") or "").strip()
        if not voice_id or not package:
            raise UiJobError("VoiceRig succeeded without voice id/package")
        raw = client.package_bytes(package)
        package_sha = hashlib.sha256(raw).hexdigest()
        feedback = f"Source-derived VoiceRig build from {job['body_revision']} via UI job {job['job_id']}"

        existing = next(
            (
                item for item in profile.get("voice_revisions", [])
                if item.get("voice_id") == voice_id
                and item.get("voice_package") == package
                and item.get("package_sha256") == package_sha
                and item.get("feedback") == feedback
            ),
            None,
        )
        if existing is None:
            profile = add_voice_revision(
                person_library(),
                str(job["person_id"]),
                voice_id=voice_id,
                voice_package=package,
                package_sha256=package_sha,
                feedback=feedback,
            )
            voice_revision = str(profile["voice_revisions"][-1]["revision_id"])
        else:
            voice_revision = str(existing["revision_id"])

        profile = load_profile(person_library(), str(job["person_id"]))
        try:
            write_source_binding(
                person_library(),
                profile,
                kind="voice",
                revision_id=voice_revision,
                evidence_kind="stash-voicerig-source-manifest-v1",
                evidence_sha256=str(evidence["manifest_sha256"]),
                evidence_ref=str(evidence["manifest_path"]),
                source_files=source_files,
            )
        except PersonSourceAlignmentError as exc:
            raise UiJobError(f"VoiceRig candidate could not be bound to exact Stash source evidence: {exc}") from exc

        binding_path = person_library() / ".source-bindings" / str(job["person_id"]) / f"{voice_revision}.json"
        job["voice_revision"] = voice_revision
        job["voice_package"] = package
        job["package_sha256"] = package_sha
        job["source_binding_sha256"] = file_sha256(binding_path)
        job["status"] = "succeeded"
        job["progress"] = 100
        job["stage"] = "complete"
        job["message"] = "VoiceRig-stemmen er bygget fra og bundet til de eksakte Stash-kilder."
        job["completed_utc"] = _now()
        job["speaker_choices"] = None
        job["reference_choices"] = None
        job["error"] = None
        _write_job(job)
        return job

    def choose_voice_speaker(self, job_id: str, anchor: str) -> dict[str, Any]:
        with self._lock:
            job = _read_job(_job_path(job_id))
        if job.get("kind") != "voice-build" or job.get("status") != "needs_speaker":
            raise UiJobError("Voice build is not waiting for speaker selection")
        profile = load_profile(person_library(), str(job["person_id"]))
        source_files_for_body(person_library(), profile, body_revision=str(job["body_revision"]))
        try:
            remote = _voicerig_client().choose_voice_job_speaker(str(job["voicerig_job_id"]), anchor)
        except (VoiceRigClientError, PersonVoiceSourceError) as exc:
            raise UiJobError(str(exc)) from exc
        with self._lock:
            current = _read_job(_job_path(job_id))
            self._apply_remote_voice_state(current, remote)
            _write_job(current)
            return current

    def choose_voice_reference(self, job_id: str, choice: int) -> dict[str, Any]:
        with self._lock:
            job = _read_job(_job_path(job_id))
        if job.get("kind") != "voice-build" or job.get("status") != "needs_reference":
            raise UiJobError("Voice build is not waiting for reference selection")
        profile = load_profile(person_library(), str(job["person_id"]))
        source_files_for_body(person_library(), profile, body_revision=str(job["body_revision"]))
        try:
            remote = _voicerig_client().choose_voice_job_reference(str(job["voicerig_job_id"]), int(choice))
        except (VoiceRigClientError, PersonVoiceSourceError, ValueError) as exc:
            raise UiJobError(str(exc)) from exc
        with self._lock:
            current = _read_job(_job_path(job_id))
            self._apply_remote_voice_state(current, remote)
            _write_job(current)
            return current

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

            manifest_path, source_files = _body_source_evidence(
                job["clone_output"],
                performer_id=str(source["performer_id"]),
            )
            manifest_sha = file_sha256(manifest_path)

            with self._lock:
                current = self.get(job_id)
                if current.get("status") != "running":
                    return
                installed = install_package(
                    package_path,
                    body_library(),
                    expected_sha256=expected_hash,
                )
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
                body_revision = updated["body_revisions"][-1]["revision_id"]
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
                    raise UiJobError(f"body candidate could not be bound to exact Stash source evidence: {exc}") from exc
                current["body_revision"] = body_revision
                current["canonical_body_id"] = body_id
                current["source_binding_sha256"] = file_sha256(
                    person_library() / ".source-bindings" / current["person_id"] / f"{body_revision}.json"
                )
                current["status"] = "succeeded"
                current["completed_utc"] = _now()
                current["pid"] = None
                _write_job(current)
        except Exception as exc:
            with self._lock:
                job = _read_job(_job_path(job_id))
                if job.get("status") not in _FINAL:
                    job["status"] = "failed"
                    job["completed_utc"] = _now()
                    job["pid"] = None
                    job["error"] = str(exc)[:4000]
                    _write_job(job)

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = _read_job(_job_path(job_id))
            if job.get("status") in _FINAL:
                return job
        if job.get("kind") == "voice-build":
            remote_id = str(job.get("voicerig_job_id") or "")
            if not remote_id:
                raise UiJobError("Voice build has no recoverable VoiceRig job id")
            try:
                remote = _voicerig_client().cancel_voice_job(remote_id)
            except VoiceRigClientError as exc:
                raise UiJobError(str(exc)) from exc
            with self._lock:
                current = _read_job(_job_path(job_id))
                self._apply_remote_voice_state(current, remote)
                _write_job(current)
                return current
        with self._lock:
            job = _read_job(_job_path(job_id))
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
