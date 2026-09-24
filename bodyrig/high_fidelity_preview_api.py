from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .ab_baseline_physical_preflight import (
    AbBaselinePhysicalPreflightError,
    run_ab_baseline_physical_preflight,
)
from .high_fidelity_anatomy_promotion import promotion_status as anatomy_promotion_status
from .high_fidelity_component_review import review_status as component_review_status
from .high_fidelity_continuation_status import (
    HighFidelityContinuationStatusError,
    inspect_continuation,
)
from .high_fidelity_hair_deformation_review import review_status as hair_deformation_review_status
from .high_fidelity_hair_promotion import promotion_status as hair_promotion_status
from .high_fidelity_preview_jobs import HighFidelityPreviewError, manager
from .high_fidelity_release_readiness import (
    HighFidelityReleaseReadinessError,
    inspect_release_readiness,
)
from .motor_v3_api import router as motor_v3_router
from .operator_launch import OperatorLaunchError, launch_canonical_operator
from .photoidentity_registry import (
    PhotoIdentityRegistryError,
    require_body_job_photoidentity_evidence,
)
from .photoidentity_fine_identity_registry import (
    PhotoIdentityFineIdentityRegistryError,
    require_body_job_photoidentical_fine_identity,
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


class HighFidelityContinuationActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["advance"] = "advance"
    inputs: dict[str, Any] = Field(default_factory=dict)


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
        require_body_job_photoidentical_fine_identity(person_id, request.body_job_id)
        return manager.start(
            person_id,
            body_job_id=request.body_job_id,
            target_family=request.target_family,
        )
    except (PhotoIdentityRegistryError, PhotoIdentityFineIdentityRegistryError, HighFidelityPreviewError) as exc:
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


def _ps_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _continuation_command_with_inputs(
    action: dict[str, Any],
    inputs: dict[str, Any],
) -> str:
    command = action.get("command")
    if not isinstance(command, str) or not command.strip():
        raise HTTPException(
            status_code=409,
            detail=str(action.get("reason") or "Continuation gate has no executable command."),
        )
    gate = str(action.get("gate") or "")
    if action.get("operator_input_required") is not True:
        return command

    quality_gates = {
        "component_review",
        "hair_deformation_review",
        "iris_review",
        "face_secondary_review",
        "hfn_human_review",
    }
    if gate in quality_gates:
        note = str(inputs.get("quality_note") or "").strip()
        if not note:
            raise HTTPException(
                status_code=422,
                detail="Denne human-review gate kræver en konkret quality note.",
            )
        if "<QUALITY_NOTE>" not in command:
            raise HTTPException(
                status_code=409,
                detail="Canonical continuation command mangler quality-note placeholder.",
            )
        return command.replace("<QUALITY_NOTE>", _ps_quote(note), 1)

    if gate == "iris_candidate":
        fields = {
            "<LEFT_CX>": "left_cx",
            "<LEFT_CY>": "left_cy",
            "<LEFT_RADIUS>": "left_radius",
            "<RIGHT_CX>": "right_cx",
            "<RIGHT_CY>": "right_cy",
            "<RIGHT_RADIUS>": "right_radius",
        }
        for placeholder, name in fields.items():
            raw = inputs.get(name)
            try:
                value = float(raw)
            except (TypeError, ValueError) as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"{name} skal være et tal.",
                ) from exc
            if name.endswith("radius") and value <= 0:
                raise HTTPException(
                    status_code=422,
                    detail=f"{name} skal være større end 0.",
                )
            command = command.replace(placeholder, format(value, ".12g"), 1)
        return command

    if gate == "hfn_detail_candidate":
        capture_id = str(inputs.get("capture_id") or "").strip()
        uv_path = str(inputs.get("uv_evidence_path") or "").strip()
        if not capture_id or not uv_path:
            raise HTTPException(
                status_code=422,
                detail="HFN detail candidate kræver capture_id og uv_evidence_path.",
            )
        if "<CAPTURE_ID>" not in command or "<UV_EVIDENCE_PATH>" not in command:
            raise HTTPException(
                status_code=409,
                detail="Canonical HFN command mangler forventede source-input placeholders.",
            )
        command = command.replace("<CAPTURE_ID>", _ps_quote(capture_id), 1)
        command = command.replace("<UV_EVIDENCE_PATH>", _ps_quote(uv_path), 1)
        return command

    if gate == "fine_identity_application":
        sweep = str(inputs.get("sweep_root") or "").strip()
        adapter = str(inputs.get("adapter_config") or "").strip()
        if not sweep or not adapter:
            raise HTTPException(
                status_code=422,
                detail="Fine-identity kræver sweep_root og adapter_config.",
            )
        if "<SWEEP_ROOT>" not in command or "<ADAPTER_CONFIG>" not in command:
            raise HTTPException(
                status_code=409,
                detail="Canonical fine-identity command mangler forventede placeholders.",
            )
        return command.replace("<SWEEP_ROOT>", _ps_quote(sweep), 1).replace(
            "<ADAPTER_CONFIG>", _ps_quote(adapter), 1
        )

    raise HTTPException(
        status_code=409,
        detail=(
            f"Gate {gate or '<unknown>'} kræver operator-input, men har endnu ingen "
            "typed UI-substitution. Den må ikke køres som rå shell fra browseren."
        ),
    )


@router.post("/api/v1/high-fidelity-preview-jobs/{job_id}/continuation-action")
def run_high_fidelity_continuation_action(
    job_id: str,
    request: HighFidelityContinuationActionRequest,
) -> dict:
    del request.action
    try:
        status = inspect_continuation(job_id)
    except HighFidelityContinuationStatusError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    action = status.get("next_gate")
    if not isinstance(action, dict):
        raise HTTPException(
            status_code=409,
            detail="High-fidelity continuation har ingen uafsluttet canonical gate.",
        )
    command = _continuation_command_with_inputs(action, request.inputs)
    authority = operator_checkout_status()
    if authority.get("ok") is not True:
        raise HTTPException(
            status_code=409,
            detail=str(authority.get("reason") or "Operator checkout is not authoritative."),
        )
    root_value = str(authority.get("root") or "").strip()
    if not root_value:
        raise HTTPException(status_code=409, detail="Operator authority has no checkout root.")
    try:
        launch = launch_canonical_operator(
            command,
            category="high-fidelity-continuation",
            context={"preview_job_id": job_id, "gate": str(action.get("gate") or "")},
            cwd=root_value,
        )
    except OperatorLaunchError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"launched": True, "launch": launch, "status": status}


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
