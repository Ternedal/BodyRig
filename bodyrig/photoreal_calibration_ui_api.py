from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from .person_profiles import PersonProfileError, load_profile
from .photoreal_calibration_ui import (
    PhotorealCalibrationUiError,
    inspect_person_calibration,
    run_person_calibration_diagnostic,
)
from .stash_source import StashClient, StashConfig, StashSourceError
from .storage import data_dir, person_library


router = APIRouter()


def _optional_stash_client() -> StashClient | None:
    url = os.environ.get("STASH_URL", "").strip()
    key = os.environ.get("STASH_API_KEY", "").strip()
    if not url or not key:
        return None
    try:
        return StashClient(StashConfig(url=url, api_key=key))
    except StashSourceError:
        return None


def _profile(person_id: str) -> dict:
    try:
        return load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get(
    "/api/v1/people/{person_id}/body/photoreal-calibration"
)
def photoreal_calibration_status(person_id: str) -> dict:
    try:
        return inspect_person_calibration(
            _profile(person_id),
            data_dir(),
            stash_client=_optional_stash_client(),
        )
    except PhotorealCalibrationUiError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post(
    "/api/v1/people/{person_id}/body/photoreal-calibration/diagnostic"
)
def photoreal_calibration_diagnostic(person_id: str) -> dict:
    try:
        return run_person_calibration_diagnostic(
            _profile(person_id),
            data_dir(),
            stash_client=_optional_stash_client(),
        )
    except PhotorealCalibrationUiError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
