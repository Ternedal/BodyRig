from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

from .hands_feet_nails_detail_candidate import (
    HandsFeetNailsDetailCandidateError,
    _candidate_id,
    build_detail_candidate,
    candidate_paths,
    validate_candidate_receipt,
)
from .hands_feet_nails_uv_domain_evidence import (
    HandsFeetNailsUvDomainEvidenceError,
    derive_uv_domain_evidence,
    evidence_path as uv_evidence_path,
    validate_uv_domain_evidence,
)
from .high_fidelity_preview_jobs import HighFidelityPreviewError, manager as preview_manager
from .package import MRBodyError, validate_package
from .storage import person_library, ui_jobs_dir
from .ui_jobs import UiJobError, manager as ui_jobs

FORMAT = "bodyrig-high-fidelity-hands-feet-nails-detail"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-hands-feet-nails-detail-v1"
JOB_RE = re.compile(r"^hfpreview-[0-9a-f]{32}$")
PERSON_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_RE = re.compile(r"^body-r[0-9]{4}$")
CAPTURE_RE = re.compile(r"^hfncap-[0-9a-f]{32}$")
CANDIDATE_RE = re.compile(r"^hfncand-[0-9a-f]{32}$")
GIT_RE = re.compile(r"^[0-9a-f]{40}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "preview_job_id",
    "body_job_id",
    "person_id",
    "body_revision",
    "body_id",
    "capture_id",
    "bodyrig_revision",
    "source_package_sha256",
    "landmark_evidence_sha256",
    "uv_evidence_sha256",
    "candidate_id",
    "candidate_receipt_sha256",
    "candidate_package_sha256",
    "source_grounded",
    "geometry_modified",
    "texture_modified",
    "human_review_required",
    "physical_acceptance_required",
    "production_activation",
}


class HighFidelityHfnDetailError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, label: str) -> str:
    text = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(text):
        raise HighFidelityHfnDetailError(f"{label} is not a canonical SHA-256")
    return text


def _job(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not JOB_RE.fullmatch(text):
        raise HighFidelityHfnDetailError("high-fidelity preview job id is not canonical")
    return text


def _revision(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not GIT_RE.fullmatch(text):
        raise HighFidelityHfnDetailError("BodyRig revision is not a canonical Git SHA")
    return text


def _capture(value: Any) -> str:
    text = str(value or "").strip().lower()
    if not CAPTURE_RE.fullmatch(text):
        raise HighFidelityHfnDetailError("HFN source capture id is not canonical")
    return text


def _authority_path(preview_job_id: str) -> Path:
    job = _job(preview_job_id)
    return (
        ui_jobs_dir()
        / ".high-fidelity-previews"
        / job
        / "continuation"
        / "hands-feet-nails-detail"
        / "authority.json"
    ).resolve()


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityHfnDetailError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise HighFidelityHfnDetailError(f"{label} must be a JSON object")
    return value


def _source_context(preview_job_id: str) -> dict[str, str]:
    job = _job(preview_job_id)
    try:
        preview = preview_manager.get(job)
    except HighFidelityPreviewError as exc:
        raise HighFidelityHfnDetailError(str(exc)) from exc
    if preview.get("status") != "succeeded":
        raise HighFidelityHfnDetailError("HFN continuation requires a succeeded high-fidelity preview")
    body_job_id = str(preview.get("body_job_id") or "").strip()
    if not body_job_id:
        raise HighFidelityHfnDetailError("high-fidelity preview has no source body-build job")
    try:
        body_job = ui_jobs.get(body_job_id)
    except UiJobError as exc:
        raise HighFidelityHfnDetailError(str(exc)) from exc
    if body_job.get("kind") != "body-build" or body_job.get("status") != "succeeded":
        raise HighFidelityHfnDetailError("HFN continuation source body-build is not succeeded")
    person_id = str(body_job.get("person_id") or "").strip().lower()
    body_revision = str(body_job.get("body_revision") or "").strip().lower()
    body_id = str(body_job.get("canonical_body_id") or "").strip()
    if not PERSON_RE.fullmatch(person_id) or not BODY_RE.fullmatch(body_revision) or not body_id:
        raise HighFidelityHfnDetailError("HFN continuation source Person/body identity is not canonical")
    if str(preview.get("canonical_body_id") or "") != body_id:
        raise HighFidelityHfnDetailError("high-fidelity preview and source body-build body ids differ")
    return {
        "preview_job_id": job,
        "body_job_id": body_job_id,
        "person_id": person_id,
        "body_revision": body_revision,
        "body_id": body_id,
    }


def _read_uv_evidence(path: Path) -> dict[str, Any]:
    raw = _read_json(path, "HFN UV-domain evidence")
    try:
        return validate_uv_domain_evidence(raw)
    except HandsFeetNailsUvDomainEvidenceError as exc:
        raise HighFidelityHfnDetailError(str(exc)) from exc


def _read_candidate(
    root: Path,
    *,
    context: Mapping[str, str],
    capture_id: str,
    candidate_id: str,
) -> tuple[dict[str, Any], Path, Path]:
    package_path, receipt_path = candidate_paths(
        root,
        context["person_id"],
        context["body_revision"],
        capture_id,
        candidate_id,
    )
    if package_path.is_file() != receipt_path.is_file():
        raise HighFidelityHfnDetailError("HFN candidate package/receipt is incomplete")
    if not package_path.is_file():
        raise HighFidelityHfnDetailError("HFN detail candidate has not been created")
    raw = _read_json(receipt_path, "HFN detail candidate receipt")
    try:
        candidate = validate_candidate_receipt(raw)
    except HandsFeetNailsDetailCandidateError as exc:
        raise HighFidelityHfnDetailError(str(exc)) from exc
    if candidate["candidate_id"] != candidate_id:
        raise HighFidelityHfnDetailError("HFN candidate path/id mismatch")
    actual_package_sha = _sha256(package_path)
    if actual_package_sha != candidate["candidate_package_sha256"]:
        raise HighFidelityHfnDetailError("HFN candidate package bytes changed after creation")
    try:
        validated = validate_package(package_path)
    except MRBodyError as exc:
        raise HighFidelityHfnDetailError(f"HFN candidate package is invalid: {exc}") from exc
    if str(validated.manifest["id"]) != context["body_id"]:
        raise HighFidelityHfnDetailError("HFN candidate changed canonical body id")
    return candidate, package_path, receipt_path


def read_hfn_detail(
    preview_job_id: str,
    *,
    source_package_path: str | os.PathLike[str],
) -> dict[str, Any]:
    context = _source_context(preview_job_id)
    source_package = Path(source_package_path).expanduser().resolve()
    if not source_package.is_file():
        raise HighFidelityHfnDetailError("HFN continuation source package is missing")
    source_sha = _sha256(source_package)
    try:
        source_validated = validate_package(source_package)
    except MRBodyError as exc:
        raise HighFidelityHfnDetailError(f"HFN continuation source package is invalid: {exc}") from exc
    if str(source_validated.manifest["id"]) != context["body_id"]:
        raise HighFidelityHfnDetailError("HFN continuation source package has different body id")

    authority_path = _authority_path(preview_job_id)
    if not authority_path.is_file():
        raise HighFidelityHfnDetailError("HFN high-fidelity detail authority is missing")
    value = _read_json(authority_path, "HFN high-fidelity detail authority")
    version = value.get("version")
    if (
        set(value) != TOP_FIELDS
        or value.get("format") != FORMAT
        or isinstance(version, bool)
        or version != VERSION
        or value.get("policy_revision") != POLICY_REVISION
    ):
        raise HighFidelityHfnDetailError("HFN high-fidelity detail authority format/version/policy mismatch")
    expected = {
        "preview_job_id": context["preview_job_id"],
        "body_job_id": context["body_job_id"],
        "person_id": context["person_id"],
        "body_revision": context["body_revision"],
        "body_id": context["body_id"],
        "source_package_sha256": source_sha,
    }
    for field, wanted in expected.items():
        if str(value.get(field) or "").lower() != str(wanted).lower():
            raise HighFidelityHfnDetailError(f"HFN detail authority no longer matches exact {field}")
    capture_id = _capture(value.get("capture_id"))
    revision = _revision(value.get("bodyrig_revision"))
    candidate_id = str(value.get("candidate_id") or "").strip().lower()
    if not CANDIDATE_RE.fullmatch(candidate_id):
        raise HighFidelityHfnDetailError("HFN candidate id is not canonical")
    landmark_sha = _sha(value.get("landmark_evidence_sha256"), "HFN landmark evidence SHA-256")
    uv_sha = _sha(value.get("uv_evidence_sha256"), "HFN UV evidence SHA-256")
    receipt_sha = _sha(value.get("candidate_receipt_sha256"), "HFN candidate receipt SHA-256")
    candidate_sha = _sha(value.get("candidate_package_sha256"), "HFN candidate package SHA-256")
    if (
        value.get("source_grounded") is not True
        or value.get("geometry_modified") is not False
        or value.get("texture_modified") is not True
        or value.get("human_review_required") is not True
        or value.get("physical_acceptance_required") is not True
        or value.get("production_activation") is not False
    ):
        raise HighFidelityHfnDetailError("HFN continuation crossed review/physical/production authority boundary")

    root = person_library().resolve()
    uv_path = uv_evidence_path(root, context["person_id"], context["body_revision"], capture_id, revision)
    if not uv_path.is_file() or _sha256(uv_path) != uv_sha:
        raise HighFidelityHfnDetailError("HFN UV evidence bytes are missing or changed")
    uv = _read_uv_evidence(uv_path)
    if (
        uv["person_id"] != context["person_id"]
        or uv["body_revision"] != context["body_revision"]
        or uv["capture_id"] != capture_id
        or uv["body_id"] != context["body_id"]
        or uv["package_sha256"] != source_sha
        or uv["landmark_evidence_sha256"] != landmark_sha
    ):
        raise HighFidelityHfnDetailError("HFN UV evidence no longer binds exact continuation package/landmark authority")

    candidate, package_path, receipt_path = _read_candidate(
        root,
        context=context,
        capture_id=capture_id,
        candidate_id=candidate_id,
    )
    if _sha256(receipt_path) != receipt_sha or _sha256(package_path) != candidate_sha:
        raise HighFidelityHfnDetailError("HFN candidate authority no longer matches exact candidate bytes")
    candidate_exact = {
        "person_id": context["person_id"],
        "body_revision": context["body_revision"],
        "capture_id": capture_id,
        "body_id": context["body_id"],
        "bodyrig_revision": revision,
        "source_package_sha256": source_sha,
        "candidate_package_sha256": candidate_sha,
        "uv_evidence_sha256": uv_sha,
    }
    for field, wanted in candidate_exact.items():
        if str(candidate.get(field) or "").lower() != str(wanted).lower():
            raise HighFidelityHfnDetailError(f"HFN candidate no longer matches exact {field}")
    return {
        **dict(value),
        "authority_path": str(authority_path),
        "uv_evidence_path": str(uv_path),
        "candidate_receipt_path": str(receipt_path),
        "package_path": str(package_path),
    }


def prepare_hfn_detail(
    preview_job_id: str,
    *,
    capture_id: str,
    landmark_evidence_path: str | os.PathLike[str],
    bodyrig_revision: str,
) -> dict[str, Any]:
    context = _source_context(preview_job_id)
    capture = _capture(capture_id)
    revision = _revision(bodyrig_revision)
    landmark_path = Path(landmark_evidence_path).expanduser().resolve()
    if not landmark_path.is_file():
        raise HighFidelityHfnDetailError("HFN landmark evidence is missing")
    landmark_sha = _sha256(landmark_path)

    # Local import avoids an import cycle: continuation status imports this module
    # only to validate the final HFN gate.
    from .high_fidelity_continuation_status import inspect_continuation

    continuation = inspect_continuation(context["preview_job_id"])
    next_gate = continuation.get("next_gate")
    if not isinstance(next_gate, Mapping) or next_gate.get("gate") != "hands_feet_nails_detail":
        raise HighFidelityHfnDetailError("HFN detail can only be prepared at the canonical final continuation gate")
    source_package = Path(str(continuation.get("current_package_path") or "")).expanduser().resolve()
    source_sha = _sha(continuation.get("current_package_sha256"), "continuation source package SHA-256")
    if not source_package.is_file() or _sha256(source_package) != source_sha:
        raise HighFidelityHfnDetailError("continuation source package bytes are missing or changed")
    try:
        source_validated = validate_package(source_package)
    except MRBodyError as exc:
        raise HighFidelityHfnDetailError(f"continuation source package is invalid: {exc}") from exc
    if str(source_validated.manifest["id"]) != context["body_id"]:
        raise HighFidelityHfnDetailError("continuation source package body id differs from source body-build")

    root = person_library().resolve()
    uv_path = uv_evidence_path(root, context["person_id"], context["body_revision"], capture, revision)
    if uv_path.exists():
        uv = _read_uv_evidence(uv_path)
        if (
            uv["person_id"] != context["person_id"]
            or uv["body_revision"] != context["body_revision"]
            or uv["capture_id"] != capture
            or uv["body_id"] != context["body_id"]
            or uv["package_sha256"] != source_sha
            or uv["landmark_evidence_sha256"] != landmark_sha
        ):
            raise HighFidelityHfnDetailError("existing create-only HFN UV evidence belongs to different exact bytes")
    else:
        try:
            result = derive_uv_domain_evidence(
                root,
                context["person_id"],
                body_revision=context["body_revision"],
                capture_id=capture,
                landmark_evidence_path=landmark_path,
                package_path=source_package,
                uv_bodyrig_revision=revision,
            )
        except HandsFeetNailsUvDomainEvidenceError as exc:
            raise HighFidelityHfnDetailError(str(exc)) from exc
        uv_path = Path(str(result["manifest"])).expanduser().resolve()
    uv_sha = _sha256(uv_path)

    candidate_id = _candidate_id(
        person_id=context["person_id"],
        body_revision=context["body_revision"],
        capture_id=capture,
        bodyrig_revision=revision,
        source_package_sha256=source_sha,
        uv_evidence_sha256=uv_sha,
    )
    candidate_package, candidate_receipt = candidate_paths(
        root,
        context["person_id"],
        context["body_revision"],
        capture,
        candidate_id,
    )
    if candidate_package.exists() != candidate_receipt.exists():
        raise HighFidelityHfnDetailError("existing HFN candidate package/receipt is incomplete")
    if not candidate_package.exists():
        try:
            build_detail_candidate(
                root,
                context["person_id"],
                body_revision=context["body_revision"],
                capture_id=capture,
                uv_evidence_path=uv_path,
                package_path=source_package,
                bodyrig_revision=revision,
            )
        except HandsFeetNailsDetailCandidateError as exc:
            raise HighFidelityHfnDetailError(str(exc)) from exc
    candidate, candidate_package, candidate_receipt = _read_candidate(
        root,
        context=context,
        capture_id=capture,
        candidate_id=candidate_id,
    )
    if candidate["source_package_sha256"] != source_sha or candidate["uv_evidence_sha256"] != uv_sha:
        raise HighFidelityHfnDetailError("HFN candidate does not bind exact continuation/UV bytes")

    authority_path = _authority_path(preview_job_id)
    authority = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        **context,
        "capture_id": capture,
        "bodyrig_revision": revision,
        "source_package_sha256": source_sha,
        "landmark_evidence_sha256": landmark_sha,
        "uv_evidence_sha256": uv_sha,
        "candidate_id": candidate_id,
        "candidate_receipt_sha256": _sha256(candidate_receipt),
        "candidate_package_sha256": _sha256(candidate_package),
        "source_grounded": True,
        "geometry_modified": False,
        "texture_modified": True,
        "human_review_required": True,
        "physical_acceptance_required": True,
        "production_activation": False,
    }
    if set(authority) != TOP_FIELDS:
        raise HighFidelityHfnDetailError("internal HFN continuation authority fields are not canonical")
    authority_path.parent.mkdir(parents=True, exist_ok=True)
    if authority_path.exists():
        existing = read_hfn_detail(preview_job_id, source_package_path=source_package)
        comparable = {key: existing[key] for key in TOP_FIELDS}
        if comparable != authority:
            raise HighFidelityHfnDetailError("HFN continuation authority already exists for different exact bytes")
        return existing
    with authority_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(authority, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return read_hfn_detail(preview_job_id, source_package_path=source_package)
