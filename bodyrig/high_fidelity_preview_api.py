from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .ab_baseline_physical_preflight import (
    AbBaselinePhysicalPreflightError,
    run_ab_baseline_physical_preflight,
)
from .high_fidelity_anatomy_promotion import promotion_status as anatomy_promotion_status
from .high_fidelity_component_review import review_status as component_review_status
from .high_fidelity_hair_deformation_review import review_status as hair_deformation_review_status
from .high_fidelity_hair_promotion import promotion_status as hair_promotion_status
from .high_fidelity_preview_jobs import HighFidelityPreviewError, manager
from .high_fidelity_release_readiness import (
    HighFidelityReleaseReadinessError,
    inspect_release_readiness,
)
from .motor_v3_api import router as motor_v3_router
from .photoidentity_registry import (
    PhotoIdentityRegistryError,
    require_body_job_photoidentity_evidence,
)
from .revision_bound_body_build import (
    RevisionBoundBodyBuildError,
    start_revision_bound_body_build,
)
from .ui_jobs import operator_checkout_status

router = APIRouter()
router.include_router(motor_v3_router)


class HighFidelityPreviewStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body_job_id: str = Field(pattern=r"^job-[0-9a-f]{32}$")
    target_family: Literal["female", "male", "neutral"]


class RevisionBoundBodyBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_bodyrig_revision: str = Field(pattern=r"^[0-9a-f]{40}$")
    expected_stash_performer_id: str = Field(min_length=1, max_length=256)
    retain_private_workspace_for_ab: bool = False


class AbBaselinePhysicalPreflightRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_bodyrig_revision: str = Field(pattern=r"^[0-9a-f]{40}$")


def _canonical_revision(value: object) -> str | None:
    revision = str(value or "").strip().lower()
    if len(revision) != 40 or any(ch not in "0123456789abcdef" for ch in revision):
        return None
    return revision


@router.get("/api/v1/operator-authority")
def get_operator_authority() -> dict:
    authority = operator_checkout_status()
    revision = _canonical_revision(authority.get("revision"))
    ready = bool(authority.get("ok"))
    reason = authority.get("reason")
    if ready and revision is None:
        ready = False
        reason = "BodyRig operator checkout reported ready without an exact Git revision"
    return {
        "ok": ready,
        "bodyrig_revision": revision,
        "reason": reason,
    }


@router.post("/api/v1/people/{person_id}/body/ab-baseline-preflight")
def preflight_exact_revision_ab_baseline(person_id: str, request: AbBaselinePhysicalPreflightRequest) -> dict:
    try:
        return run_ab_baseline_physical_preflight(
            person_id,
            expected_bodyrig_revision=request.expected_bodyrig_revision,
        )
    except AbBaselinePhysicalPreflightError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/v1/people/{person_id}/body/build-revision-bound")
def start_exact_revision_body_build(person_id: str, request: RevisionBoundBodyBuildRequest) -> dict:
    try:
        return start_revision_bound_body_build(
            person_id,
            expected_bodyrig_revision=request.expected_bodyrig_revision,
            expected_stash_performer_id=request.expected_stash_performer_id,
            retain_private_workspace_for_ab=request.retain_private_workspace_for_ab,
        )
    except RevisionBoundBodyBuildError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/v1/people/{person_id}/body/high-fidelity-preview")
def start_high_fidelity_preview(person_id: str, request: HighFidelityPreviewStartRequest) -> dict:
    try:
        # A coarse body-build is not authority for another human-review render.
        # Require a separately collected, exact-hash source-sufficiency receipt
        # so missing identity-critical regions cannot be silently filled by a
        # generic human prior and presented to the operator as a clone.
        require_body_job_photoidentity_evidence(person_id, request.body_job_id)
        return manager.start(
            person_id,
            body_job_id=request.body_job_id,
            target_family=request.target_family,
        )
    except (PhotoIdentityRegistryError, HighFidelityPreviewError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/v1/high-fidelity-preview-jobs/{job_id}")
def get_high_fidelity_preview_job(job_id: str) -> dict:
    try:
        return manager.get(job_id)
    except HighFidelityPreviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/high-fidelity-preview-jobs/{job_id}/component-review")
def get_high_fidelity_component_review(job_id: str) -> dict:
    status = component_review_status(job_id)
    if status.get("state") == "unavailable":
        raise HTTPException(status_code=404, detail=str(status.get("reason") or "component review unavailable"))
    return status


@router.get("/api/v1/high-fidelity-preview-jobs/{job_id}/anatomy-promotion")
def get_high_fidelity_anatomy_promotion(job_id: str) -> dict:
    return anatomy_promotion_status(job_id)


@router.get("/api/v1/high-fidelity-preview-jobs/{job_id}/hair-deformation-review")
def get_high_fidelity_hair_deformation_review(job_id: str) -> dict:
    return hair_deformation_review_status(job_id)


@router.get("/api/v1/high-fidelity-preview-jobs/{job_id}/hair-promotion")
def get_high_fidelity_hair_promotion(job_id: str) -> dict:
    return hair_promotion_status(job_id)


@router.get("/api/v1/high-fidelity-preview-jobs/{job_id}/continuation-status")
def get_high_fidelity_continuation_status(job_id: str) -> dict:
    try:
        return inspect_release_readiness(job_id)
    except HighFidelityReleaseReadinessError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/people/{person_id}/body/high-fidelity-preview")
def latest_high_fidelity_preview(
    person_id: str,
    revision: str = Query(min_length=1, max_length=24),
) -> dict:
    try:
        job = manager.latest_for_revision(person_id, revision)
    except HighFidelityPreviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job.get("status") == "succeeded":
        job = dict(job)
        job["views"] = [
            {
                **view,
                "url": f"/api/v1/high-fidelity-preview-jobs/{job['job_id']}/image/{view['view']}",
            }
            for view in job.get("views", [])
        ]
    return job


@router.get("/api/v1/high-fidelity-preview-jobs/{job_id}/image/{view}")
def high_fidelity_preview_image(job_id: str, view: str):
    try:
        path = manager.image_path(job_id, view)
    except HighFidelityPreviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})
