from __future__ import annotations

from fastapi import APIRouter, HTTPException

from .models import BodyCueV2


router = APIRouter()


def _runtime():
    # Imported lazily so this extension router can be registered while
    # bodyrig.app is still being constructed, while still using the one
    # canonical runtime instance owned by the application.
    from .app import runtime

    return runtime


@router.post("/api/v2/runtime/cue")
def apply_cue_v2(cue: BodyCueV2) -> dict:
    try:
        return _runtime().apply_cue(cue).__dict__
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/api/v3/runtime/motor-state")
def motor_state_v3() -> dict:
    try:
        return _runtime().motor_state_v3()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
