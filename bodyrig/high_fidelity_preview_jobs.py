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

from .person_profiles import PersonProfileError, load_profile
from .storage import person_library, ui_jobs_dir
from .ui_jobs import UiJobError, manager as ui_jobs, operator_checkout_status

FORMAT = "bodyrig-high-fidelity-preview-job"
VERSION = 1
TARGET_FAMILIES = {"female", "male", "neutral"}
FINAL = {"succeeded", "failed", "interrupted"}
VIEW_NAMES = (
    "front-full",
    "three-quarter-full",
    "side-full",
    "face-front",
    "face-zoom",
    "eyes-closeup",
)
CANONICAL_VIEWS = VIEW_NAMES[:4]
ROOT_DIRNAME = ".high-fidelity-previews"


class HighFidelityPreviewError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _store_root() -> Path:
    return ui_jobs_dir() / ROOT_DIRNAME


def _job_root(job_id: str) -> Path:
    return _store_root() / job_id


def _job_path(job_id: str) -> Path:
    return _job_root(job_id) / "job.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityPreviewError(f"{label} is unreadable JSON: {path}") from exc
    if not isinstance(value, dict):
        raise HighFidelityPreviewError(f"{label} must be a JSON object: {path}")
    return value


def _write_job(job: dict[str, Any]) -> None:
    path = _job_path(str(job["job_id"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temp.write_text(
            json.dumps(job, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _read_job(path: Path) -> dict[str, Any]:
    value = _read_json(path, label="High-fidelity preview job")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise HighFidelityPreviewError(f"unsupported high-fidelity preview job: {path}")
    job_id = str(value.get("job_id") or "")
    if path != _job_path(job_id):
        raise HighFidelityPreviewError("high-fidelity preview job id/path mismatch")
    return value


def _inside(root: Path, path: Path, *, label: str) -> Path:
    root = root.resolve()
    path = path.expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HighFidelityPreviewError(f"{label} escaped its persisted job root") from exc
    return path


def _need_file(root: Path, value: str | os.PathLike[str], *, label: str) -> Path:
    path = _inside(root, Path(value), label=label)
    if not path.is_file():
        raise HighFidelityPreviewError(f"{label} is missing: {path}")
    return path


def _need_dir(root: Path, value: str | os.PathLike[str], *, label: str) -> Path:
    path = _inside(root, Path(value), label=label)
    if not path.is_dir():
        raise HighFidelityPreviewError(f"{label} is missing: {path}")
    return path


def _registered_body(profile: dict[str, Any], revision: str) -> dict[str, Any]:
    item = next((value for value in profile.get("body_revisions", []) if value.get("revision_id") == revision), None)
    if not isinstance(item, dict):
        raise HighFidelityPreviewError("baseline body revision is no longer registered for this person")
    package = Path(str(item.get("package_path") or "")).expanduser().resolve()
    if not package.is_file():
        raise HighFidelityPreviewError("registered baseline body package is missing")
    if _sha256(package) != str(item.get("package_sha256") or ""):
        raise HighFidelityPreviewError("registered baseline body package bytes changed after body build")
    return item


def _body_job_authority(person_id: str, body_job_id: str) -> tuple[dict[str, Any], dict[str, Any], Path]:
    try:
        body_job = ui_jobs.get(body_job_id)
    except UiJobError as exc:
        raise HighFidelityPreviewError(str(exc)) from exc
    if body_job.get("kind") != "body-build" or body_job.get("status") != "succeeded":
        raise HighFidelityPreviewError("high-fidelity preview requires a succeeded physical body-build job")
    if str(body_job.get("person_id") or "") != person_id:
        raise HighFidelityPreviewError("body-build job belongs to a different person")
    body_revision = str(body_job.get("body_revision") or "")
    canonical_body_id = str(body_job.get("canonical_body_id") or "")
    bodyrig_revision = str(body_job.get("bodyrig_revision") or "").lower()
    if not body_revision or not canonical_body_id or len(bodyrig_revision) != 40:
        raise HighFidelityPreviewError("body-build job lacks canonical revision/identity authority")

    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HighFidelityPreviewError(str(exc)) from exc
    registered = _registered_body(profile, body_revision)
    if str(registered.get("body_id") or "") != canonical_body_id:
        raise HighFidelityPreviewError("body-build canonical body id no longer matches the registered revision")

    body_root = (ui_jobs_dir() / body_job_id).resolve()
    clone_output = Path(str(body_job.get("clone_output") or "")).expanduser().resolve()
    try:
        clone_output.relative_to(body_root)
    except ValueError as exc:
        raise HighFidelityPreviewError("body-build clone output escaped its persisted UI job root") from exc
    if not clone_output.is_dir():
        raise HighFidelityPreviewError("body-build clone output is missing")
    retained = clone_output / "retained-anatomy-source"
    if not retained.is_dir():
        raise HighFidelityPreviewError(
            "body-build has no retained-anatomy-source continuation workspace; rerun the body build on a retention-capable revision"
        )
    return body_job, profile, retained


def _checkout_revision(expected: str) -> dict[str, Any]:
    authority = operator_checkout_status()
    if not authority.get("ok"):
        raise HighFidelityPreviewError(str(authority.get("reason") or "BodyRig operator checkout is not authoritative"))
    actual = str(authority.get("revision") or "").lower()
    if actual != expected.lower():
        raise HighFidelityPreviewError(
            "high-fidelity continuation requires the exact BodyRig revision that produced the baseline body; "
            f"expected {expected.lower()}, got {actual or 'unknown'}"
        )
    return authority


def _validate_completed(job: dict[str, Any]) -> dict[str, Any]:
    if job.get("status") != "succeeded":
        raise HighFidelityPreviewError("high-fidelity preview is not complete")
    job_id = str(job["job_id"])
    root = _job_root(job_id).resolve()
    expected_revision = str(job.get("bodyrig_revision") or "").lower()
    target_family = str(job.get("target_family") or "")
    canonical_body_id = str(job.get("canonical_body_id") or "")
    if target_family not in TARGET_FAMILIES:
        raise HighFidelityPreviewError("persisted high-fidelity target family is invalid")

    anatomy_dir = _need_dir(root, str(job.get("anatomy_run_root") or ""), label="Anatomy run root")
    summary_path = _need_file(root, anatomy_dir / "subject-anatomy-physical-gate.json", label="Anatomy gate summary")
    summary = _read_json(summary_path, label="Anatomy gate summary")
    if (
        summary.get("format") != "bodyrig-subject-anatomy-physical-gate"
        or summary.get("version") != 1
        or str(summary.get("bodyrig_revision") or "").lower() != expected_revision
        or summary.get("target_model_family") != target_family
        or summary.get("canonical_body_id") != canonical_body_id
        or summary.get("candidate_gross_anatomy_pass") is not True
        or summary.get("comparison_only") is not True
        or summary.get("human_review_required") is not True
        or summary.get("production_activation") is not False
    ):
        raise HighFidelityPreviewError("persisted anatomy gate no longer satisfies the comparison-only authority contract")

    candidate_package = _need_file(root, str(summary.get("package") or ""), label="Anatomy candidate package")
    candidate_sha = _sha256(candidate_package)
    if str(summary.get("package_sha256") or "") != candidate_sha:
        raise HighFidelityPreviewError("anatomy candidate package hash no longer matches its gate summary")

    component_dir = _need_dir(root, str(job.get("component_root") or ""), label="Component discovery root")
    component_path = _need_file(root, component_dir / "subject-component-discovery.json", label="Component discovery receipt")
    component = _read_json(component_path, label="Component discovery receipt")
    runtime = component.get("runtime")
    eyes = component.get("eyes")
    if not isinstance(runtime, dict) or not isinstance(eyes, dict):
        raise HighFidelityPreviewError("component discovery receipt lacks hair/eye runtime authority")
    if (
        component.get("format") != "bodyrig-subject-component-discovery"
        or component.get("version") != 1
        or str(component.get("bodyrig_revision") or "").lower() != expected_revision
        or component.get("target_model_family") != target_family
        or component.get("anatomy_gate_summary_sha256") != _sha256(summary_path)
        or component.get("candidate_package_sha256") != candidate_sha
        or component.get("comparison_only") is not True
        or component.get("human_review_required") is not True
        or component.get("high_fidelity_ready") is not False
        or component.get("production_activation") is not False
        or runtime.get("source_hair_runtime_applied") is not True
        or runtime.get("source_eye_surface_applied") is not True
        or runtime.get("corneal_material_status") != "runtime-applied"
        or runtime.get("production_activation") is not False
    ):
        raise HighFidelityPreviewError("component discovery no longer satisfies the review-only hair/eye authority contract")

    review_vrm = _need_file(root, str(runtime.get("review_vrm") or ""), label="Combined source hair+eye review VRM")
    review_vrm_sha = _sha256(review_vrm)
    if runtime.get("review_vrm_sha256") != review_vrm_sha:
        raise HighFidelityPreviewError("combined source hair+eye review VRM hash changed")
    runtime_receipt = _need_file(root, str(runtime.get("evidence") or ""), label="Combined hair+eye runtime receipt")
    if runtime.get("evidence_sha256") != _sha256(runtime_receipt):
        raise HighFidelityPreviewError("combined hair+eye runtime receipt hash changed")
    runtime_value = _read_json(runtime_receipt, label="Combined hair+eye runtime receipt")
    if (
        runtime_value.get("format") != "bodyrig-source-hair-eye-review-runtime"
        or runtime_value.get("version") != 1
        or str(runtime_value.get("bodyrigRevision") or "").lower() != expected_revision
        or runtime_value.get("packageSha256") != candidate_sha
        or runtime_value.get("reviewVrmSha256") != review_vrm_sha
        or runtime_value.get("sourceHairRuntimeApplied") is not True
        or runtime_value.get("sourceEyeSurfaceApplied") is not True
        or runtime_value.get("cornealMaterialStatus") != "runtime-applied"
        or runtime_value.get("comparisonOnly") is not True
        or runtime_value.get("hairComponentAuthority") is not False
        or runtime_value.get("eyeComponentAuthority") is not False
        or runtime_value.get("productionActivation") is not False
    ):
        raise HighFidelityPreviewError("combined hair+eye runtime receipt no longer validates")

    preview_dir = _need_dir(root, str(job.get("preview_output") or ""), label="Hair+eye preview output")
    comparison_path = _need_file(root, preview_dir / "comparison-authority.json", label="Preview comparison authority")
    comparison = _read_json(comparison_path, label="Preview comparison authority")
    if (
        comparison.get("authority") != "source-hair-eye-review-runtime"
        or comparison.get("review_avatar_sha256") != review_vrm_sha
        or comparison.get("source_hair_runtime_applied") is not True
        or comparison.get("source_eye_surface_applied") is not True
        or comparison.get("corneal_material_status") != "runtime-applied"
        or comparison.get("physical_acceptance_authority") is not False
        or comparison.get("production_activation") is not False
    ):
        raise HighFidelityPreviewError("hair+eye preview comparison authority no longer validates")

    manifest_path = _need_file(root, preview_dir / "snapshots" / "fidelity-render-set.json", label="Preview snapshot manifest")
    manifest = _read_json(manifest_path, label="Preview snapshot manifest")
    snapshots = manifest.get("snapshots")
    if not isinstance(snapshots, list) or [str(item.get("view") or "") for item in snapshots if isinstance(item, dict)] != list(CANONICAL_VIEWS):
        raise HighFidelityPreviewError("hair+eye preview snapshot manifest no longer contains the four canonical views")

    views: list[dict[str, str]] = []
    snapshot_root = preview_dir / "snapshots"
    for name in VIEW_NAMES:
        path = _need_file(root, snapshot_root / f"{name}.png", label=f"High-fidelity preview {name}")
        views.append({"view": name, "sha256": _sha256(path)})

    return {
        "candidate_package_sha256": candidate_sha,
        "review_vrm_sha256": review_vrm_sha,
        "anatomy_gate_sha256": _sha256(summary_path),
        "component_discovery_sha256": _sha256(component_path),
        "comparison_authority_sha256": _sha256(comparison_path),
        "target_family": target_family,
        "semantics": "visual-fidelity-not-identity-verification",
        "iris_identity_status": str(eyes.get("iris_appearance_status") or "review-pending"),
        "eyelash_status": str(eyes.get("eyelash_status") or "missing"),
        "comparison_only": True,
        "human_review_required": True,
        "production_activation": False,
        "views": views,
    }


def _public(job: dict[str, Any]) -> dict[str, Any]:
    value = {
        key: job.get(key)
        for key in (
            "format",
            "version",
            "job_id",
            "kind",
            "person_id",
            "body_job_id",
            "body_revision",
            "canonical_body_id",
            "target_family",
            "bodyrig_revision",
            "status",
            "progress",
            "stage",
            "message",
            "created_utc",
            "started_utc",
            "completed_utc",
            "error",
        )
    }
    value["comparison_only"] = True
    value["production_activation"] = False
    if job.get("status") == "succeeded":
        value.update(_validate_completed(job))
    return value


class HighFidelityPreviewManager:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._reconcile_interrupted()

    def _reconcile_interrupted(self) -> None:
        root = _store_root()
        if not root.exists():
            return
        for path in root.glob("*/job.json"):
            try:
                job = _read_job(path)
            except HighFidelityPreviewError:
                continue
            if job.get("status") in {"queued", "running"}:
                job["status"] = "interrupted"
                job["completed_utc"] = _now()
                job["stage"] = "interrupted"
                job["message"] = "BodyRig restarted before the high-fidelity preview reached a terminal state."
                job["error"] = "Retry explicitly; persisted comparison evidence was not promoted."
                job["pid"] = None
                _write_job(job)

    def _existing(self, *, person_id: str, body_job_id: str, target_family: str) -> dict[str, Any] | None:
        root = _store_root()
        if not root.exists():
            return None
        matches: list[dict[str, Any]] = []
        for path in root.glob("*/job.json"):
            try:
                job = _read_job(path)
            except HighFidelityPreviewError:
                continue
            if (
                job.get("person_id") == person_id
                and job.get("body_job_id") == body_job_id
                and job.get("target_family") == target_family
                and job.get("status") in {"queued", "running", "succeeded"}
            ):
                matches.append(job)
        return sorted(matches, key=lambda value: str(value.get("created_utc") or ""), reverse=True)[0] if matches else None

    def start(self, person_id: str, *, body_job_id: str, target_family: str) -> dict[str, Any]:
        target_family = str(target_family or "").strip().lower()
        if target_family not in TARGET_FAMILIES:
            raise HighFidelityPreviewError("target_family must be explicitly female, male or neutral")
        body_job, profile, retained = _body_job_authority(person_id, body_job_id)
        bodyrig_revision = str(body_job["bodyrig_revision"]).lower()
        _checkout_revision(bodyrig_revision)

        with self._lock:
            existing = self._existing(person_id=person_id, body_job_id=body_job_id, target_family=target_family)
            if existing is not None:
                return _public(existing)
            job_id = f"hfpreview-{uuid.uuid4().hex}"
            root = _job_root(job_id)
            job = {
                "format": FORMAT,
                "version": VERSION,
                "job_id": job_id,
                "kind": "high-fidelity-preview",
                "person_id": person_id,
                "body_job_id": body_job_id,
                "body_revision": str(body_job["body_revision"]),
                "canonical_body_id": str(body_job["canonical_body_id"]),
                "target_family": target_family,
                "bodyrig_revision": bodyrig_revision,
                "display_name": str(profile["display_name"]),
                "baseline_clone_output": str(Path(str(body_job["clone_output"])).resolve()),
                "retained_anatomy_source": str(retained.resolve()),
                "status": "queued",
                "progress": 0,
                "stage": "queued",
                "message": "High-fidelity anatomy/hair/eye preview venter på operator-pipelinen.",
                "created_utc": _now(),
                "started_utc": None,
                "completed_utc": None,
                "pid": None,
                "log_path": str(root / "job.log"),
                "anatomy_run_root": str(root / "anatomy"),
                "component_root": str(root / "components"),
                "preview_output": str(root / "windows-preview"),
                "error": None,
            }
            _write_job(job)
            thread = threading.Thread(target=self._run, args=(job_id,), name=f"bodyrig-{job_id}", daemon=True)
            thread.start()
            return _public(job)

    def _set_phase(self, job_id: str, *, progress: int, stage: str, message: str) -> dict[str, Any]:
        with self._lock:
            job = _read_job(_job_path(job_id))
            if job.get("status") != "running":
                raise HighFidelityPreviewError("high-fidelity preview job is no longer running")
            job["progress"] = progress
            job["stage"] = stage
            job["message"] = message
            _write_job(job)
            return job

    def _run_command(self, job_id: str, args: list[str], *, label: str) -> int:
        with self._lock:
            job = _read_job(_job_path(job_id))
            if job.get("status") != "running":
                raise HighFidelityPreviewError("high-fidelity preview job is no longer running")
            expected = str(job["bodyrig_revision"])
            _checkout_revision(expected)
            log_path = Path(str(job["log_path"]))
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log = log_path.open("a", encoding="utf-8", newline="\n")
            try:
                log.write(f"\n[{_now()}] RUN {label}\n")
                log.flush()
                process = subprocess.Popen(
                    args,
                    cwd=str(_repo_root()),
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    env=os.environ.copy(),
                )
                self._processes[job_id] = process
                job["pid"] = process.pid
                _write_job(job)
            except Exception:
                log.close()
                raise
        try:
            code = process.wait()
        finally:
            log.close()
            with self._lock:
                self._processes.pop(job_id, None)
                current = _read_job(_job_path(job_id))
                current["pid"] = None
                _write_job(current)
        _checkout_revision(expected)
        return int(code)

    def _run(self, job_id: str) -> None:
        try:
            with self._lock:
                job = _read_job(_job_path(job_id))
                if job.get("status") != "queued":
                    return
                job["status"] = "running"
                job["started_utc"] = _now()
                job["stage"] = "anatomy"
                job["message"] = "Kører comparison-only subject anatomy gate fra retained source geometry."
                job["progress"] = 10
                _write_job(job)

            expected = str(job["bodyrig_revision"])
            _checkout_revision(expected)
            ps = shutil.which("pwsh")
            if not ps:
                raise HighFidelityPreviewError("PowerShell 7+ executable (pwsh) was not found")
            root = _repo_root()

            anatomy_args = [
                ps,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "run-subject-anatomy-physical-gate.ps1"),
                "-BaselineCloneOutput",
                str(job["baseline_clone_output"]),
                "-IdentityWorkspace",
                str(job["retained_anatomy_source"]),
                "-TargetFamily",
                str(job["target_family"]),
                "-RunRoot",
                str(job["anatomy_run_root"]),
                "-BodyId",
                str(job["canonical_body_id"]),
                "-Name",
                str(job["display_name"]),
                "-BodyRigPython",
                sys.executable,
            ]
            code = self._run_command(job_id, anatomy_args, label="subject anatomy physical gate")
            if code != 0:
                raise HighFidelityPreviewError(
                    f"subject anatomy gate stopped with exit code {code}; inspect persisted comparison evidence before retrying"
                )

            self._set_phase(
                job_id,
                progress=55,
                stage="components",
                message="Anatomy machine-gate er grøn; udleder source-hår, øjengeometri og source-baket øjenoverflade.",
            )
            component_args = [
                ps,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "run-subject-component-discovery.ps1"),
                "-AnatomyRunRoot",
                str(job["anatomy_run_root"]),
                "-IdentityWorkspace",
                str(job["retained_anatomy_source"]),
                "-OutputRoot",
                str(job["component_root"]),
            ]
            code = self._run_command(job_id, component_args, label="subject component discovery")
            if code != 0:
                raise HighFidelityPreviewError(f"hair/eye component discovery failed with exit code {code}")

            anatomy_summary = _read_json(
                Path(str(job["anatomy_run_root"])) / "subject-anatomy-physical-gate.json",
                label="Anatomy gate summary",
            )
            package_path = Path(str(anatomy_summary.get("package") or "")).expanduser().resolve()

            self._set_phase(
                job_id,
                progress=82,
                stage="windows-preview",
                message="Source hair+eye review-VRM er klar; renderer front/¾/side/face/eye-closeup i Unity.",
            )
            preview_args = [
                ps,
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(root / "run-source-hair-eye-windows-preview.ps1"),
                "-PackagePath",
                str(package_path),
                "-ReviewRuntimeDir",
                str(Path(str(job["component_root"])) / "runtime"),
                "-OutputDir",
                str(job["preview_output"]),
                "-BodyRigPython",
                sys.executable,
            ]
            code = self._run_command(job_id, preview_args, label="source hair+eye Windows preview")
            if code != 0:
                raise HighFidelityPreviewError(f"hair+eye Windows preview failed with exit code {code}")

            with self._lock:
                current = _read_job(_job_path(job_id))
                current["status"] = "succeeded"
                current["progress"] = 100
                current["stage"] = "review-ready"
                current["message"] = "Seks exact-hash high-fidelity review-billeder er klar i Person Studio."
                current["completed_utc"] = _now()
                current["pid"] = None
                current["error"] = None
                _write_job(current)
                _validate_completed(current)
        except Exception as exc:
            with self._lock:
                try:
                    current = _read_job(_job_path(job_id))
                except HighFidelityPreviewError:
                    return
                if current.get("status") not in FINAL:
                    current["status"] = "failed"
                    current["stage"] = "failed"
                    current["message"] = "High-fidelity continuation stoppede fail-closed; baseline body revision er uændret."
                    current["completed_utc"] = _now()
                    current["pid"] = None
                    current["error"] = str(exc)[:4000]
                    _write_job(current)

    def get(self, job_id: str) -> dict[str, Any]:
        path = _job_path(job_id)
        if not path.is_file():
            raise HighFidelityPreviewError("high-fidelity preview job not found")
        return _public(_read_job(path))

    def latest_for_revision(self, person_id: str, body_revision: str) -> dict[str, Any]:
        root = _store_root()
        if not root.exists():
            raise HighFidelityPreviewError("no high-fidelity preview exists for this body revision")
        matches: list[dict[str, Any]] = []
        for path in root.glob("*/job.json"):
            try:
                job = _read_job(path)
            except HighFidelityPreviewError:
                continue
            if job.get("person_id") == person_id and job.get("body_revision") == body_revision:
                matches.append(job)
        if not matches:
            raise HighFidelityPreviewError("no high-fidelity preview exists for this body revision")
        latest = sorted(matches, key=lambda value: str(value.get("created_utc") or ""), reverse=True)[0]
        return _public(latest)

    def image_path(self, job_id: str, view: str) -> Path:
        if view not in VIEW_NAMES:
            raise HighFidelityPreviewError("unknown high-fidelity preview view")
        job = _read_job(_job_path(job_id))
        proof = _validate_completed(job)
        expected = next((item["sha256"] for item in proof["views"] if item["view"] == view), None)
        if not expected:
            raise HighFidelityPreviewError("high-fidelity preview view is not in validated evidence")
        root = _job_root(job_id).resolve()
        preview_dir = _need_dir(root, str(job.get("preview_output") or ""), label="Hair+eye preview output")
        path = _need_file(root, preview_dir / "snapshots" / f"{view}.png", label=f"High-fidelity preview {view}")
        if _sha256(path) != expected:
            raise HighFidelityPreviewError("high-fidelity preview image bytes changed after validation")
        return path


manager = HighFidelityPreviewManager()
