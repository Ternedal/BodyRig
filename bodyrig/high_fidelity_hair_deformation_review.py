from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .high_fidelity_component_review import (
    HighFidelityComponentReviewError,
    read_review as read_component_review,
)
from .high_fidelity_preview_jobs import ROOT_DIRNAME, HighFidelityPreviewError, manager as preview_jobs
from .storage import ui_jobs_dir

FORMAT = "bodyrig-high-fidelity-hair-deformation-review"
VERSION = 1
POLICY_REVISION = "bodyrig-high-fidelity-hair-deformation-review-v1"
JOB_RE = re.compile(r"^hfpreview-[0-9a-f]{32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
REVISION_RE = re.compile(r"^[0-9a-f]{40}$")
CHECKLIST_FIELDS = {
    "head_turn_sequence_reviewed",
    "hair_head_attachment_acceptable",
    "hair_clipping_acceptable",
    "hair_silhouette_stable_during_turn",
    "hair_restoration_to_neutral_acceptable",
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
    "candidate_package_sha256",
    "review_vrm_sha256",
    "component_review_sha256",
    "comparison_authority_sha256",
    "hair_deformation_probe_sha256",
    "sequence_revision",
    "machine_metrics",
    "reviewed_utc",
    "checklist",
    "quality_note",
    "hair_promotion_eligible",
    "human_review_complete",
    "production_activation",
}


class HighFidelityHairDeformationReviewError(RuntimeError):
    pass


def _job_id(value: str) -> str:
    clean = str(value or "").strip().lower()
    if not JOB_RE.fullmatch(clean):
        raise HighFidelityHairDeformationReviewError("high-fidelity preview job id is not canonical")
    return clean


def _sha(value: Any, *, label: str) -> str:
    clean = str(value or "").strip().lower()
    if not SHA_RE.fullmatch(clean):
        raise HighFidelityHairDeformationReviewError(f"{label} is not a canonical SHA-256")
    return clean


def _revision(value: Any) -> str:
    clean = str(value or "").strip().lower()
    if not REVISION_RE.fullmatch(clean):
        raise HighFidelityHairDeformationReviewError("BodyRig revision is not canonical")
    return clean


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HighFidelityHairDeformationReviewError(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise HighFidelityHairDeformationReviewError(f"{label} must be a JSON object")
    return value


def _preview_root(preview_job_id: str) -> Path:
    return (ui_jobs_dir() / ROOT_DIRNAME / _job_id(preview_job_id)).resolve()


def _need_file(root: Path, path: Path, *, label: str) -> Path:
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HighFidelityHairDeformationReviewError(f"{label} escaped persisted preview authority") from exc
    if not path.is_file():
        raise HighFidelityHairDeformationReviewError(f"{label} is missing: {path}")
    return path


def _machine_authority(preview_job_id: str) -> dict[str, Any]:
    job_id = _job_id(preview_job_id)
    try:
        preview = preview_jobs.get(job_id)
    except HighFidelityPreviewError as exc:
        raise HighFidelityHairDeformationReviewError(f"high-fidelity preview authority failed: {exc}") from exc
    if preview.get("status") != "succeeded":
        raise HighFidelityHairDeformationReviewError("hair deformation review requires a succeeded high-fidelity preview")
    try:
        component_review = read_component_review(job_id)
    except HighFidelityComponentReviewError as exc:
        raise HighFidelityHairDeformationReviewError(f"component visual review authority failed: {exc}") from exc
    if component_review.get("review_outcome", {}).get("hair") != "visual-pass-deformation-review-required":
        raise HighFidelityHairDeformationReviewError("hair deformation review requires the canonical visual hair pass")
    if component_review.get("promotion_eligibility", {}).get("hair") is not False:
        raise HighFidelityHairDeformationReviewError("component visual review unexpectedly pre-authorized hair promotion")

    root = _preview_root(job_id)
    preview_dir = _need_file(root, root / "job.json", label="Preview job authority").parent
    # The job JSON stores the canonical output path; use the validated public preview only
    # to identify the job and then constrain evidence to this job root.
    raw_job = _read_json(preview_dir / "job.json", label="Preview job authority")
    output = Path(str(raw_job.get("preview_output") or "")).expanduser().resolve()
    try:
        output.relative_to(root)
    except ValueError as exc:
        raise HighFidelityHairDeformationReviewError("preview output escaped persisted preview authority") from exc
    if not output.is_dir():
        raise HighFidelityHairDeformationReviewError("persisted Windows preview output is missing")

    comparison_path = _need_file(root, output / "comparison-authority.json", label="Hair+eye comparison authority")
    probe_path = _need_file(root, output / "hair-deformation-probe.json", label="Hair deformation machine probe")
    comparison = _read_json(comparison_path, label="Hair+eye comparison authority")
    probe = _read_json(probe_path, label="Hair deformation machine probe")
    probe_sha = _sha256(probe_path)

    if (
        comparison.get("authority") != "source-hair-eye-review-runtime"
        or comparison.get("hair_deformation_probe_sha256") != probe_sha
        or comparison.get("hair_deformation_machine_pass") is not True
        or comparison.get("hair_deformation_human_review_required") is not True
        or comparison.get("physical_acceptance_authority") is not False
        or comparison.get("production_activation") is not False
    ):
        raise HighFidelityHairDeformationReviewError("comparison authority does not bind a canonical hair deformation machine PASS")

    expected_revision = _revision(preview.get("bodyrig_revision"))
    expected_package = _sha(preview.get("candidate_package_sha256"), label="preview candidate package SHA-256")
    expected_avatar = _sha(preview.get("review_vrm_sha256"), label="preview review VRM SHA-256")
    if (
        probe.get("format") != "bodyrig-hair-deformation-probe"
        or probe.get("version") != 1
        or str(probe.get("bodyrig_revision") or "").lower() != expected_revision
        or probe.get("platform") != "windows-unity-univrm"
        or probe.get("package_sha256") != expected_package
        or probe.get("avatar_sha256") != expected_avatar
        or probe.get("sequence_revision") != "source-hair-head-turn-v1"
        or probe.get("hair_node") != "BodyRigSourceHairReview"
        or probe.get("hair_mesh") != "BodyRigSourceHairReviewMesh"
        or probe.get("skinned_mesh_renderer_found") is not True
        or probe.get("head_bone_resolved") is not True
        or probe.get("head_bone_bound") is not True
        or probe.get("vertex_motion_observed") is not True
        or probe.get("restored_neutral") is not True
        or probe.get("complete") is not True
        or probe.get("human_review_required") is not True
        or probe.get("comparison_only") is not True
        or probe.get("hair_component_authority") is not False
        or probe.get("production_activation") is not False
    ):
        raise HighFidelityHairDeformationReviewError("hair deformation machine probe is stale, incomplete or activating")

    numeric = {
        "observed_head_turn_degrees": (18.2, None),
        "vertex_motion_rms_m": (0.00025, None),
        "vertex_motion_max_m": (0.001, None),
        "restoration_rms_m": (0.0, 0.00025),
        "restoration_max_m": (0.0, 0.001),
    }
    metrics: dict[str, float] = {}
    for field, (minimum, maximum) in numeric.items():
        value = probe.get(field)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise HighFidelityHairDeformationReviewError(f"hair deformation metric {field} is invalid")
        number = float(value)
        if number < minimum or (maximum is not None and number > maximum):
            raise HighFidelityHairDeformationReviewError(f"hair deformation metric {field} is outside canonical thresholds")
        metrics[field] = number

    component_review_path = next(
        (path for path in (ui_jobs_dir() / ".high-fidelity-component-reviews").glob(f"{job_id}.*.json") if path.is_file()),
        None,
    )
    if component_review_path is None:
        raise HighFidelityHairDeformationReviewError("component visual-review receipt file is missing")
    if _sha256(component_review_path) != _sha256(component_review_path):
        raise HighFidelityHairDeformationReviewError("component visual-review receipt hash is unstable")

    return {
        "preview": preview,
        "component_review": component_review,
        "component_review_sha256": _sha256(component_review_path),
        "comparison_authority_sha256": _sha256(comparison_path),
        "hair_deformation_probe_sha256": probe_sha,
        "machine_metrics": metrics,
    }


def review_path(preview_job_id: str, *, hair_probe_sha256: str) -> Path:
    job_id = _job_id(preview_job_id)
    probe_sha = _sha(hair_probe_sha256, label="hair deformation probe SHA-256")
    return ui_jobs_dir() / ".high-fidelity-hair-deformation-reviews" / f"{job_id}.{probe_sha}.json"


def write_review(
    preview_job_id: str,
    *,
    bodyrig_revision: str,
    checklist: Mapping[str, Any],
    quality_note: str,
) -> dict[str, Any]:
    authority = _machine_authority(preview_job_id)
    preview = authority["preview"]
    expected_revision = _revision(preview.get("bodyrig_revision"))
    supplied_revision = _revision(bodyrig_revision)
    if supplied_revision != expected_revision:
        raise HighFidelityHairDeformationReviewError(
            f"hair deformation review checkout revision mismatch: expected {expected_revision}, got {supplied_revision}"
        )
    normalized = dict(checklist)
    if set(normalized) != CHECKLIST_FIELDS:
        raise HighFidelityHairDeformationReviewError("hair deformation review checklist fields are not canonical")
    for field in CHECKLIST_FIELDS:
        if normalized.get(field) is not True:
            raise HighFidelityHairDeformationReviewError(f"hair deformation review did not explicitly pass {field}")
    note = str(quality_note or "").strip()
    if not note:
        raise HighFidelityHairDeformationReviewError("hair deformation review requires a non-empty quality note")
    if len(note) > 4000:
        raise HighFidelityHairDeformationReviewError("hair deformation review quality note exceeds 4000 characters")

    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "policy_revision": POLICY_REVISION,
        "preview_job_id": str(preview["job_id"]),
        "person_id": str(preview["person_id"]),
        "body_revision": str(preview["body_revision"]),
        "canonical_body_id": str(preview["canonical_body_id"]),
        "bodyrig_revision": expected_revision,
        "candidate_package_sha256": _sha(preview["candidate_package_sha256"], label="candidate package SHA-256"),
        "review_vrm_sha256": _sha(preview["review_vrm_sha256"], label="review VRM SHA-256"),
        "component_review_sha256": authority["component_review_sha256"],
        "comparison_authority_sha256": authority["comparison_authority_sha256"],
        "hair_deformation_probe_sha256": authority["hair_deformation_probe_sha256"],
        "sequence_revision": "source-hair-head-turn-v1",
        "machine_metrics": dict(authority["machine_metrics"]),
        "reviewed_utc": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "checklist": {field: True for field in sorted(CHECKLIST_FIELDS)},
        "quality_note": note,
        "hair_promotion_eligible": True,
        "human_review_complete": True,
        "production_activation": False,
    }
    path = review_path(str(preview["job_id"]), hair_probe_sha256=receipt["hair_deformation_probe_sha256"])
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError as exc:
        raise HighFidelityHairDeformationReviewError(f"refusing to overwrite existing hair deformation review: {path}") from exc
    return receipt


def read_review(preview_job_id: str) -> dict[str, Any]:
    authority = _machine_authority(preview_job_id)
    preview = authority["preview"]
    path = review_path(str(preview["job_id"]), hair_probe_sha256=authority["hair_deformation_probe_sha256"])
    if not path.is_file():
        raise HighFidelityHairDeformationReviewError(f"hair deformation human review is missing: {path}")
    value = _read_json(path, label="Hair deformation human review")
    if set(value) != TOP_FIELDS:
        raise HighFidelityHairDeformationReviewError("hair deformation review fields are not canonical")
    if value.get("format") != FORMAT or value.get("version") != VERSION or value.get("policy_revision") != POLICY_REVISION:
        raise HighFidelityHairDeformationReviewError("hair deformation review format/version/policy mismatch")
    expected = {
        "preview_job_id": str(preview["job_id"]),
        "person_id": str(preview["person_id"]),
        "body_revision": str(preview["body_revision"]),
        "canonical_body_id": str(preview["canonical_body_id"]),
        "bodyrig_revision": _revision(preview["bodyrig_revision"]),
        "candidate_package_sha256": _sha(preview["candidate_package_sha256"], label="candidate package SHA-256"),
        "review_vrm_sha256": _sha(preview["review_vrm_sha256"], label="review VRM SHA-256"),
        "component_review_sha256": authority["component_review_sha256"],
        "comparison_authority_sha256": authority["comparison_authority_sha256"],
        "hair_deformation_probe_sha256": authority["hair_deformation_probe_sha256"],
        "sequence_revision": "source-hair-head-turn-v1",
        "machine_metrics": authority["machine_metrics"],
        "hair_promotion_eligible": True,
        "human_review_complete": True,
        "production_activation": False,
    }
    for field, expected_value in expected.items():
        if value.get(field) != expected_value:
            raise HighFidelityHairDeformationReviewError(f"hair deformation review no longer matches exact authority: {field}")
    checklist = value.get("checklist")
    if not isinstance(checklist, dict) or set(checklist) != CHECKLIST_FIELDS or any(checklist.get(field) is not True for field in CHECKLIST_FIELDS):
        raise HighFidelityHairDeformationReviewError("hair deformation review checklist is not fully passed")
    if not str(value.get("quality_note") or "").strip():
        raise HighFidelityHairDeformationReviewError("hair deformation review quality note is empty")
    return value


def review_status(preview_job_id: str) -> dict[str, Any]:
    try:
        authority = _machine_authority(preview_job_id)
    except HighFidelityHairDeformationReviewError as exc:
        return {"state": "blocked", "passed": False, "reason": str(exc), "hair_promotion_eligible": False, "production_activation": False}
    path = review_path(preview_job_id, hair_probe_sha256=authority["hair_deformation_probe_sha256"])
    if not path.is_file():
        return {
            "state": "required",
            "passed": False,
            "reason": "Hair machine deformation PASS exists; explicit physical clipping/attachment/deformation review is still required.",
            "machine_pass": True,
            "hair_promotion_eligible": False,
            "production_activation": False,
        }
    try:
        value = read_review(preview_job_id)
    except HighFidelityHairDeformationReviewError as exc:
        return {"state": "invalid", "passed": False, "reason": str(exc), "hair_promotion_eligible": False, "production_activation": False}
    return {
        "state": "pass",
        "passed": True,
        "reviewed_utc": value["reviewed_utc"],
        "machine_pass": True,
        "hair_promotion_eligible": True,
        "production_activation": False,
    }
