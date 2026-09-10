from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from .photoidentity_evidence import PhotoIdentityEvidenceError, validate_bundle
from .storage import ui_jobs_dir
from .ui_jobs import UiJobError, manager as ui_jobs

FORMAT = "bodyrig-photoidentity-body-job-authority"
VERSION = 1
DIRNAME = "photoidentity-evidence"
RECEIPT_NAME = "photoidentity-authority.json"
REPORT_NAME = "photoidentity-evidence.json"
OBSERVATIONS_NAME = "photoidentity-observations.json"


class PhotoIdentityRegistryError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityRegistryError(f"photoidentity registry file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _job_authority(body_job_id: str) -> tuple[dict[str, Any], str, str, Path, str]:
    try:
        job = ui_jobs.get(body_job_id)
    except UiJobError as exc:
        raise PhotoIdentityRegistryError(str(exc)) from exc
    if job.get("kind") != "body-build" or job.get("status") != "succeeded":
        raise PhotoIdentityRegistryError("photoidentity authority requires a succeeded body-build job")
    person_id = str(job.get("person_id") or "").strip()
    revision = str(job.get("bodyrig_revision") or "").strip().lower()
    if not person_id or len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        raise PhotoIdentityRegistryError("body-build lacks canonical Person/BodyRig revision authority")
    source_authority = job.get("source_enqueue_authority")
    if not isinstance(source_authority, dict):
        raise PhotoIdentityRegistryError(
            "body-build predates exact source enqueue authority; photoidentity evidence cannot be attached retroactively"
        )
    if (
        source_authority.get("format") != "bodyrig-body-build-source-enqueue-authority"
        or source_authority.get("version") != 1
        or source_authority.get("job_id") != body_job_id
        or source_authority.get("person_id") != person_id
        or str(source_authority.get("expected_bodyrig_revision") or "").lower() != revision
    ):
        raise PhotoIdentityRegistryError("body-build source enqueue authority is invalid")
    performer_id = str(source_authority.get("stash_performer_id") or "").strip()
    if not performer_id:
        raise PhotoIdentityRegistryError("body-build source authority lacks Stash performer identity")
    job_root = (ui_jobs_dir() / body_job_id).resolve()
    clone_output = Path(str(job.get("clone_output") or "")).expanduser().resolve()
    try:
        clone_output.relative_to(job_root)
    except ValueError as exc:
        raise PhotoIdentityRegistryError("body-build clone output escaped its persisted job root") from exc
    baseline_manifest = clone_output / "bodyrig-stash-source-manifest.json"
    if not baseline_manifest.is_file():
        raise PhotoIdentityRegistryError("body-build baseline Stash source manifest is missing")
    return job, performer_id, revision, job_root, _sha256(baseline_manifest)


def _write_json_create_only(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise PhotoIdentityRegistryError(f"photoidentity registry output already exists: {path}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def register_body_job_photoidentity_evidence(
    body_job_id: str,
    *,
    report_path: str | Path,
    observation_path: str | Path | None = None,
) -> dict[str, Any]:
    job, performer_id, revision, job_root, baseline_sha = _job_authority(body_job_id)
    report_source = Path(report_path).expanduser().resolve()
    observations_source = (
        Path(observation_path).expanduser().resolve()
        if observation_path is not None
        else report_source.with_name(OBSERVATIONS_NAME)
    )
    try:
        report = validate_bundle(
            report_source,
            observations_source,
            require_sufficient=True,
            expected_performer_id=performer_id,
            expected_bodyrig_revision=revision,
            expected_baseline_source_manifest_sha256=baseline_sha,
        )
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityRegistryError(str(exc)) from exc

    root = job_root / DIRNAME
    if root.exists():
        raise PhotoIdentityRegistryError(
            "body-build photoidentity authority is create-only; existing evidence must not be overwritten"
        )
    root.mkdir(parents=True, exist_ok=False)
    destination_report = root / REPORT_NAME
    destination_observations = root / OBSERVATIONS_NAME
    receipt_path = root / RECEIPT_NAME
    try:
        shutil.copyfile(report_source, destination_report)
        shutil.copyfile(observations_source, destination_observations)
        if _sha256(destination_report) != _sha256(report_source) or _sha256(destination_observations) != _sha256(observations_source):
            raise PhotoIdentityRegistryError("photoidentity registry copy hash mismatch")
        # Revalidate the persisted bytes, not just their source copies.
        persisted = validate_bundle(
            destination_report,
            destination_observations,
            require_sufficient=True,
            expected_performer_id=performer_id,
            expected_bodyrig_revision=revision,
            expected_baseline_source_manifest_sha256=baseline_sha,
        )
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "body_job_id": body_job_id,
            "person_id": str(job["person_id"]),
            "stash_performer_id": performer_id,
            "bodyrig_revision": revision,
            "baseline_source_manifest_sha256": baseline_sha,
            "observation_evidence_sha256": _sha256(destination_observations),
            "sufficiency_report_sha256": _sha256(destination_report),
            "source_evidence_sufficient": persisted["source_evidence_sufficient"],
            "reconstruction_permitted": persisted["reconstruction_permitted"],
            "human_review_render_permitted": persisted["human_review_render_permitted"],
            "generic_guessing_permitted": False,
            "production_activation": False,
        }
        _write_json_create_only(receipt_path, receipt)
        return {**receipt, "receipt_path": str(receipt_path)}
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def require_body_job_photoidentity_evidence(person_id: str, body_job_id: str) -> dict[str, Any]:
    job, performer_id, revision, job_root, baseline_sha = _job_authority(body_job_id)
    if str(job.get("person_id") or "") != str(person_id):
        raise PhotoIdentityRegistryError("photoidentity body-build belongs to a different Person")
    root = job_root / DIRNAME
    receipt_path = root / RECEIPT_NAME
    report_path = root / REPORT_NAME
    observations_path = root / OBSERVATIONS_NAME
    if not receipt_path.is_file() or not report_path.is_file() or not observations_path.is_file():
        raise PhotoIdentityRegistryError(
            "photoidentity source sufficiency is not registered for this body-build; high-fidelity preview remains blocked"
        )
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityRegistryError("photoidentity body-job authority receipt is invalid JSON") from exc
    required = {
        "format",
        "version",
        "body_job_id",
        "person_id",
        "stash_performer_id",
        "bodyrig_revision",
        "baseline_source_manifest_sha256",
        "observation_evidence_sha256",
        "sufficiency_report_sha256",
        "source_evidence_sufficient",
        "reconstruction_permitted",
        "human_review_render_permitted",
        "generic_guessing_permitted",
        "production_activation",
    }
    if set(receipt) != required or receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise PhotoIdentityRegistryError("photoidentity body-job authority receipt format/fields are invalid")
    expected = {
        "body_job_id": body_job_id,
        "person_id": str(person_id),
        "stash_performer_id": performer_id,
        "bodyrig_revision": revision,
        "baseline_source_manifest_sha256": baseline_sha,
        "observation_evidence_sha256": _sha256(observations_path),
        "sufficiency_report_sha256": _sha256(report_path),
        "source_evidence_sufficient": True,
        "reconstruction_permitted": True,
        "human_review_render_permitted": True,
        "generic_guessing_permitted": False,
        "production_activation": False,
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise PhotoIdentityRegistryError(f"photoidentity body-job authority mismatch: {field}")
    try:
        return validate_bundle(
            report_path,
            observations_path,
            require_sufficient=True,
            expected_performer_id=performer_id,
            expected_bodyrig_revision=revision,
            expected_baseline_source_manifest_sha256=baseline_sha,
        )
    except PhotoIdentityEvidenceError as exc:
        raise PhotoIdentityRegistryError(str(exc)) from exc
