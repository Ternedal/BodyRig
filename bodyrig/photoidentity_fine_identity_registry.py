from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any, Mapping

from .photoidentity_fine_identity_attestation import (
    PhotoIdentityFineIdentityAttestationError,
    read_attestation,
)
from .photoidentity_registry import (
    DIRNAME as BASE_DIRNAME,
    OBSERVATIONS_NAME,
    RECEIPT_NAME as BASE_RECEIPT_NAME,
    REPORT_NAME,
    PhotoIdentityRegistryError,
    _job_authority,
    require_body_job_photoidentity_evidence,
)

FORMAT = "bodyrig-photoidentity-fine-identity-body-job-authority"
VERSION = 1
DIRNAME = "photoidentity-fine-identity-authority"
RECEIPT_NAME = "fine-identity-authority.json"
ATTESTATION_NAME = "fine-identity-source-attestation.json"


class PhotoIdentityFineIdentityRegistryError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise PhotoIdentityFineIdentityRegistryError(f"fine-identity registry file is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PhotoIdentityFineIdentityRegistryError(f"{label} is unreadable JSON") from exc
    if not isinstance(value, dict):
        raise PhotoIdentityFineIdentityRegistryError(f"{label} must be a JSON object")
    return value


def _write_json_create_only(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise PhotoIdentityFineIdentityRegistryError(f"fine-identity authority already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temp.write_text(
            json.dumps(dict(value), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def register_body_job_fine_identity_authority(body_job_id: str, *, sweep_root: Path) -> dict[str, Any]:
    try:
        job, performer_id, revision, job_root, _ = _job_authority(body_job_id)
        person_id = str(job["person_id"])
        require_body_job_photoidentity_evidence(person_id, body_job_id)
    except PhotoIdentityRegistryError as exc:
        raise PhotoIdentityFineIdentityRegistryError(str(exc)) from exc

    sweep_root = sweep_root.expanduser().resolve()
    source_attestation = sweep_root / "photoidentity-fine-identity-attestation.json"
    anatomy_observations = sweep_root / "anatomy-attested-evidence" / "photoidentity-observations.json"
    anatomy_report = sweep_root / "anatomy-attested-evidence" / "photoidentity-evidence.json"
    try:
        fine = read_attestation(
            source_attestation,
            expected_performer_id=performer_id,
            expected_bodyrig_revision=revision,
            expected_anatomy_observation_sha256=_sha256(anatomy_observations),
            expected_anatomy_report_sha256=_sha256(anatomy_report),
        )
    except PhotoIdentityFineIdentityAttestationError as exc:
        raise PhotoIdentityFineIdentityRegistryError(str(exc)) from exc

    base_root = job_root / BASE_DIRNAME
    base_receipt = base_root / BASE_RECEIPT_NAME
    base_observations = base_root / OBSERVATIONS_NAME
    base_report = base_root / REPORT_NAME
    if _sha256(base_observations) != _sha256(anatomy_observations):
        raise PhotoIdentityFineIdentityRegistryError("registered photoidentity observations do not match fine-identity anatomy lineage")
    if _sha256(base_report) != _sha256(anatomy_report):
        raise PhotoIdentityFineIdentityRegistryError("registered photoidentity report does not match fine-identity anatomy lineage")

    root = job_root / DIRNAME
    if root.exists():
        raise PhotoIdentityFineIdentityRegistryError("fine-identity body-job authority is create-only")
    root.mkdir(parents=True, exist_ok=False)
    copied_attestation = root / ATTESTATION_NAME
    receipt_path = root / RECEIPT_NAME
    try:
        shutil.copyfile(source_attestation, copied_attestation)
        if _sha256(copied_attestation) != _sha256(source_attestation):
            raise PhotoIdentityFineIdentityRegistryError("fine-identity attestation copy hash mismatch")
        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "body_job_id": body_job_id,
            "person_id": person_id,
            "stash_performer_id": performer_id,
            "bodyrig_revision": revision,
            "base_photoidentity_authority_sha256": _sha256(base_receipt),
            "base_observation_evidence_sha256": _sha256(base_observations),
            "base_sufficiency_report_sha256": _sha256(base_report),
            "fine_identity_attestation_sha256": _sha256(copied_attestation),
            "attested_domains": list(fine["attested_domains"]),
            "photoidentical_identity_detail_authority": True,
            "generic_guessing_permitted": False,
            "production_activation": False,
        }
        _write_json_create_only(receipt_path, receipt)
        return {**receipt, "receipt_path": str(receipt_path)}
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def require_body_job_photoidentical_fine_identity(person_id: str, body_job_id: str) -> dict[str, Any]:
    try:
        job, performer_id, revision, job_root, _ = _job_authority(body_job_id)
        if str(job.get("person_id") or "") != str(person_id):
            raise PhotoIdentityFineIdentityRegistryError("fine-identity body-build belongs to a different Person")
        require_body_job_photoidentity_evidence(person_id, body_job_id)
    except PhotoIdentityRegistryError as exc:
        raise PhotoIdentityFineIdentityRegistryError(str(exc)) from exc

    root = job_root / DIRNAME
    receipt_path = root / RECEIPT_NAME
    attestation_path = root / ATTESTATION_NAME
    base_root = job_root / BASE_DIRNAME
    base_receipt = base_root / BASE_RECEIPT_NAME
    base_observations = base_root / OBSERVATIONS_NAME
    base_report = base_root / REPORT_NAME
    if not receipt_path.is_file() or not attestation_path.is_file():
        raise PhotoIdentityFineIdentityRegistryError(
            "photoidentical fine-identity authority is not registered for this body-build"
        )
    receipt = _read_json(receipt_path, label="Fine-identity body-job authority")
    required = {
        "format",
        "version",
        "body_job_id",
        "person_id",
        "stash_performer_id",
        "bodyrig_revision",
        "base_photoidentity_authority_sha256",
        "base_observation_evidence_sha256",
        "base_sufficiency_report_sha256",
        "fine_identity_attestation_sha256",
        "attested_domains",
        "photoidentical_identity_detail_authority",
        "generic_guessing_permitted",
        "production_activation",
    }
    if set(receipt) != required or receipt.get("format") != FORMAT or receipt.get("version") != VERSION:
        raise PhotoIdentityFineIdentityRegistryError("fine-identity body-job authority fields are invalid")
    expected = {
        "body_job_id": body_job_id,
        "person_id": str(person_id),
        "stash_performer_id": performer_id,
        "bodyrig_revision": revision,
        "base_photoidentity_authority_sha256": _sha256(base_receipt),
        "base_observation_evidence_sha256": _sha256(base_observations),
        "base_sufficiency_report_sha256": _sha256(base_report),
        "fine_identity_attestation_sha256": _sha256(attestation_path),
        "photoidentical_identity_detail_authority": True,
        "generic_guessing_permitted": False,
        "production_activation": False,
    }
    for field, value in expected.items():
        if receipt.get(field) != value:
            raise PhotoIdentityFineIdentityRegistryError(f"fine-identity body-job authority mismatch: {field}")

    try:
        attestation = read_attestation(
            attestation_path,
            expected_performer_id=performer_id,
            expected_bodyrig_revision=revision,
            expected_anatomy_observation_sha256=_sha256(base_observations),
            expected_anatomy_report_sha256=_sha256(base_report),
        )
    except PhotoIdentityFineIdentityAttestationError as exc:
        raise PhotoIdentityFineIdentityRegistryError(str(exc)) from exc
    if list(attestation["attested_domains"]) != list(receipt["attested_domains"]):
        raise PhotoIdentityFineIdentityRegistryError("fine-identity registered domain set changed")
    return {
        **receipt,
        "attestation": attestation,
        "receipt_path": str(receipt_path),
        "receipt_sha256": _sha256(receipt_path),
    }
