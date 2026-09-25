from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .digital_twin_control_plane_ui import (
    DigitalTwinControlPlaneError,
    advance_person_digital_twin_m5,
    inspect_person_digital_twin_readiness,
)
from .person_profiles import PersonProfileError, load_profile
from .storage import person_library
from .ui_jobs import manager as ui_jobs


router = APIRouter()


class DigitalTwinControlActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: str = Field(pattern=r"^advance-m5$")


@router.get("/api/v1/people/{person_id}/digital-twin-readiness")
def digital_twin_readiness(person_id: str) -> dict:
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    try:
        return inspect_person_digital_twin_readiness(
            profile,
            ui_jobs.list(person_id=person_id),
            library_root=person_library(),
            operator_root=Path(__file__).resolve().parents[1],
        )
    except DigitalTwinControlPlaneError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

@router.post("/api/v1/people/{person_id}/digital-twin-readiness/action")
def digital_twin_readiness_action(
    person_id: str,
    request: DigitalTwinControlActionRequest,
) -> dict:
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if request.action != "advance-m5":
        raise HTTPException(status_code=422, detail="Ukendt digital-twin handling.")

    try:
        return advance_person_digital_twin_m5(
            profile,
            ui_jobs.list(person_id=person_id),
            library_root=person_library(),
            operator_root=Path(__file__).resolve().parents[1],
        )
    except DigitalTwinControlPlaneError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

