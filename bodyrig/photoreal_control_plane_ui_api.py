from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .person_profiles import PersonProfileError, load_profile
from .photoreal_control_plane_ui import (
    PhotorealControlPlaneError,
    advance_person_control_plane,
    inspect_person_control_plane,
)
from .storage import person_library


router = APIRouter()


class PhotorealControlActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(default="advance", pattern=r"^advance$")
    inputs: dict[str, Any] = Field(default_factory=dict)


def _profile(person_id: str) -> dict:
    try:
        return load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/api/v1/people/{person_id}/body/photoreal-control-plane")
def photoreal_control_plane_status(person_id: str) -> dict:
    try:
        return inspect_person_control_plane(_profile(person_id))
    except PhotorealControlPlaneError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/v1/people/{person_id}/body/photoreal-control-plane/action")
def photoreal_control_plane_action(
    person_id: str,
    request: PhotorealControlActionRequest,
) -> dict:
    try:
        return advance_person_control_plane(
            _profile(person_id),
            operator_inputs=request.inputs,
        )
    except PhotorealControlPlaneError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
