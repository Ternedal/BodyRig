from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .high_fidelity_preview_jobs import (
    HighFidelityPreviewError,
    VIEW_NAMES,
    manager as preview_jobs,
)
from .storage import ui_jobs_dir

FORMAT = "bodyrig-high-fidelity-component-review"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-component-review-v1"
JOB_RE = re.compile(r"^hfpreview-[0-9a-f]{32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
CHECKLIST_FIELDS = {
    "full_body_multiview_reviewed",
    "anatomy_geometry_acceptable",
    "hair_silhouette_acceptable",
    "face_closeup_reviewed",
    "eyes_closeup_reviewed",
    "source_hair_eye_runtime_visually_consistent",
}
REVIEW_OUTCOME = {
    "body_anatomy": "pass",
    "hair": "visual-pass-deformation-review-required",
    "eyes": "visual-pass-iris-authority-required",
}
PROMOTION_ELIGIBILITY = {
    "body_anatomy": True,
    "hair": False,
    "eyes": False,
}
TOP_FIELDS = {
    "format",
    "version",
    "policy_revision",
    "preview_job_id",
    "person_id",
    "body_revision",
    "canonical_body_id",
    "bodyrig_revision",
    "target_family",
    "candidate_package_sha256",
    "anatomy_gate_sha256",
    "component_discovery_sha256",
    "review_vrm_sha256",
    "comparison_authority_sha256",
    "view_sha256",
    "reviewed_utc",
    "checklist",
    "quality_note",
    "review_outcome",
    "promotion_eligibility",
    "human_review_complete",
    "production_activation",
}


class HighFidelityComponentReviewError(RuntimeError):
    pass


def _canonical_job_id(value: str) -> str:
    job_id = str(value or "").strip().lower()
    if not JOB_RE.fullmatch(job_id):
        raise HighFidelityComponentReviewError("high-fidelity preview job id is not canonical")
    return job_id


def _sha(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(clean):
        raise HighFidelityComponentReviewError(f"{label} is not a canonical SHA-256")
    return clean


def _preview_authority(preview_job_id: str) -> dict[str, Any]:
    job_id = _canonical_job_id(preview_job_id)
    try:
        value = preview_jobs.get(job_id)
    except HighFidelityPreviewError as exc:
        raise HighFidelityComponentReviewError(f"high-fidelity preview authority failed: {exc}") from exc
    if value.get("status") != "succeeded":
        raise HighFidelityComponentReviewError("component review requires a succeeded high-fidelity preview job")
    if value.get("comparison_only") is not True or value.get("production_activation") is not False:
        raise HighFidelityComponentReviewError("preview job crossed the comparison-only authority boundary")
    if str(value.get("semantics") or "") != "visual-fidelity-not-identity-verification":
        raise HighFidelityComponentReviewError("preview job semantics are not the canonical visual-fidelity review semantics")
    if str(value.get("iris_identity_status") or "") != "review-pending":
        raise HighFidelityComponentReviewError(
            "component-review v1 expects iris identity to remain explicitly review-pending"
        )

    for field in (
        "candidate_package_sha256",
        "anatomy_gate_sha256",
        "component_discovery_sha256",
        "review_vrm_sha256",
        "comparison_authority_sha256",
    ):
        _sha(value.get(field), label=field)
    bodyrig_revision = str(value.get("bodyrig_revision") or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", bodyrig_revision):
        raise HighFidelityComponentReviewError("preview BodyRig revision is not canonical")
    if str(value.get("target_family") or "") not in {"female", "male", "neutral"}:
        raise HighFidelityComponentReviewError("preview target family is invalid")

    views = value.get("views")
    if not isinstance(views, list) or [item.get("view") for item in views if isinstance(item, dict)] != list(VIEW_NAMES):
        raise HighFidelityComponentReviewError("preview job does not expose the six canonical/diagnostic review views")
    for item in views:
        if not isinstance(item, dict):
            raise HighFidelityComponentReviewError("preview view authority is invalid")
        _sha(item.get("sha256"), label=f"preview view {item.get('view')} SHA-256")
    return value


def _view_hashes(preview: Mapping[str, Any]) -> dict[str, str]:
    views = preview.get("views")
    if not isinstance(views, list):
        raise HighFidelityComponentReviewError("preview views are unavailable")
    return {str(item["view"]): _sha(item.get("sha256"), label=f"preview view {item.get('view')} SHA-256") for item in views}


def review_path(preview_job_id: str, *, review_vrm_sha256: str) -> Path:
    job_id = _canonical_job_id(preview_job_id)
    review_vrm_sha = _sha(review_vrm_sha256, label="review VRM SHA-256")
    root = ui_jobs_dir() / ".high-fidelity-component-reviews"
    return root / f"{job_id}.{review_vrm_sha}.json"


def write_review(
    preview_job_id: str,
    *,
    bodyrig_revision: str,
    checklist: Mapping[str, Any],
    quality_note: str,
) -> dict[str, Any]:
    preview = _preview_authority(preview_job_id)
    expected_revision = str(preview["bodyrig_revision"]).lower()
    supplied_revision = str(bodyrig_revision or "").strip().lower()
    if supplied_revision != expected_revision:
        raise HighFidelityComponentReviewError(
            f"component review checkout revision mismatch: expected {expected_revision}, got {supplied_revision or 'missing'}"
        )

    normalized = dict(checklist)
    if set(normalized) != CHECKLIST_FIELDS:
        raise HighFidelityComponentReviewError("component visual-review checklist fields are not canonical")
    for field in CHECKLIST_FIELDS:
        if normalized.get(field) is not True:
            raise HighFidelityComponentReviewError(f"component visual review did not explicitly pass {field}")
    note = str(quality_note or "").strip()
    if not note:
        raise HighFidelityComponentReviewError("component visual review requires a non-empty quality note")
    if len(note) > 4000:
        raise HighFidelityComponentReviewError("component visual review quality note exceeds 4000 characters")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "preview_job_id": str(preview["job_id"]),
        "person_id": str(preview["person_id"]),
        "body_revision": str(preview["body_revision"]),
        "canonical_body_id": str(preview["canonical_body_id"]),
        "bodyrig_revision": expected_revision,
        "target_family": str(preview["target_family"]),
        "candidate_package_sha256": _sha(preview["candidate_package_sha256"], label="candidate package SHA-256"),
        "anatomy_gate_sha256": _sha(preview["anatomy_gate_sha256"], label="anatomy gate SHA-256"),
        "component_discovery_sha256": _sha(preview["component_discovery_sha256"], label="component discovery SHA-256"),
        "review_vrm_sha256": _sha(preview["review_vrm_sha256"], label="review VRM SHA-256"),
        "comparison_authority_sha256": _sha(preview["comparison_authority_sha256"], label="comparison authority SHA-256"),
        "view_sha256": _view_hashes(preview),
        "reviewed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "checklist": {field: True for field in sorted(CHECKLIST_FIELDS)},
        "quality_note": note,
        "review_outcome": dict(REVIEW_OUTCOME),
        "promotion_eligibility": dict(PROMOTION_ELIGIBILITY),
        "human_review_complete": True,
        "production_activation": False,
    }
    path = review_path(str(preview["job_id"]), review_vrm_sha256=receipt["review_vrm_sha256"])
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise HighFidelityComponentReviewError(f"refusing to overwrite existing component review: {path}") from exc
    return receipt


def read_review(preview_job_id: str) -> dict[str, Any]:
    preview = _preview_authority(preview_job_id)
    path = review_path(str(preview["job_id"]), review_vrm_sha256=str(preview["review_vrm_sha256"]))
    if not path.is_file():
        raise HighFidelityComponentReviewError(f"component visual review is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityComponentReviewError(f"component visual review is unreadable: {path}") from exc
    if not isinstance(value, dict) or set(value) != TOP_FIELDS:
        raise HighFidelityComponentReviewError("component visual review fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise HighFidelityComponentReviewError("component visual review format/version/policy mismatch")

    exact_fields = (
        "preview_job_id",
        "person_id",
        "body_revision",
        "canonical_body_id",
        "bodyrig_revision",
        "target_family",
        "candidate_package_sha256",
        "anatomy_gate_sha256",
        "component_discovery_sha256",
        "review_vrm_sha256",
        "comparison_authority_sha256",
    )
    for field in exact_fields:
        if str(value.get(field) or "") != str(preview.get(field if field != "preview_job_id" else "job_id") or ""):
            raise HighFidelityComponentReviewError(f"component visual review no longer matches preview authority: {field}")
    if value.get("view_sha256") != _view_hashes(preview):
        raise HighFidelityComponentReviewError("component visual review no longer matches exact preview image bytes")
    checklist = value.get("checklist")
    if not isinstance(checklist, dict) or set(checklist) != CHECKLIST_FIELDS:
        raise HighFidelityComponentReviewError("component visual review checklist is not canonical")
    if any(checklist.get(field) is not True for field in CHECKLIST_FIELDS):
        raise HighFidelityComponentReviewError("component visual review checklist is not fully passed")
    if not str(value.get("quality_note") or "").strip():
        raise HighFidelityComponentReviewError("component visual review quality note is empty")
    if value.get("review_outcome") != REVIEW_OUTCOME:
        raise HighFidelityComponentReviewError("component visual review outcome crossed the v1 authority boundary")
    if value.get("promotion_eligibility") != PROMOTION_ELIGIBILITY:
        raise HighFidelityComponentReviewError("component promotion eligibility crossed the v1 authority boundary")
    if value.get("human_review_complete") is not True:
        raise HighFidelityComponentReviewError("component visual review is incomplete")
    if value.get("production_activation") is not False:
        raise HighFidelityComponentReviewError("component visual review must remain independently non-activating")
    return value


def review_status(preview_job_id: str) -> dict[str, Any]:
    try:
        preview = _preview_authority(preview_job_id)
    except HighFidelityComponentReviewError as exc:
        return {"state": "unavailable", "passed": False, "reason": str(exc)}
    path = review_path(str(preview["job_id"]), review_vrm_sha256=str(preview["review_vrm_sha256"]))
    if not path.is_file():
        return {
            "state": "required",
            "passed": False,
            "reason": "Explicit visual component review is required for this exact six-view preview evidence.",
            "promotion_eligibility": dict(PROMOTION_ELIGIBILITY),
            "review_outcome": dict(REVIEW_OUTCOME),
        }
    receipt = read_review(str(preview["job_id"]))
    return {
        "state": "pass",
        "passed": True,
        "reason": None,
        "reviewed_utc": receipt["reviewed_utc"],
        "quality_note": receipt["quality_note"],
        "policy_revision": receipt["policy_revision"],
        "promotion_eligibility": dict(PROMOTION_ELIGIBILITY),
        "review_outcome": dict(REVIEW_OUTCOME),
    }
