from __future__ import annotations

import os
from typing import Annotated

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .app import DEFAULT_HOST, DEFAULT_PORT, app, person_library
from .personality_authoring import (
    PersonalityAuthoringError,
    build_guided_personality,
    save_guided_personality,
)

Ratio = Annotated[float, Field(ge=0.0, le=1.0)]


class GuidedCommunication(BaseModel):
    model_config = ConfigDict(extra="forbid")
    directness: Ratio = 0.5
    warmth: Ratio = 0.5
    playfulness: Ratio = 0.5
    formality: Ratio = 0.5
    verbosity: Ratio = 0.5
    initiative: Ratio = 0.5


class GuidedPersonalityRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_language: str = Field(default="da", min_length=2, max_length=16)
    communication: GuidedCommunication
    authored_notes: str = Field(default="", max_length=16_000)
    style_exemplars: list[str] = Field(default_factory=list, max_length=12)
    body_revision: str | None = Field(default=None, max_length=24)


class GuidedPersonalitySaveRequest(GuidedPersonalityRequest):
    feedback: str = Field(default="", max_length=8000)


def _preview(person_id: str, request: GuidedPersonalityRequest) -> dict:
    try:
        return build_guided_personality(
            person_library(),
            person_id,
            default_language=request.default_language,
            communication=request.communication.model_dump(),
            authored_notes=request.authored_notes,
            style_exemplars=request.style_exemplars,
            body_revision=request.body_revision,
        )
    except PersonalityAuthoringError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/people/{person_id}/personality/guided/preview")
def guided_personality_preview(person_id: str, request: GuidedPersonalityRequest) -> dict:
    return _preview(person_id, request)


@app.post("/api/v1/people/{person_id}/personality/guided/revisions")
def guided_personality_revision(person_id: str, request: GuidedPersonalitySaveRequest) -> dict:
    try:
        result = save_guided_personality(
            person_library(),
            person_id,
            default_language=request.default_language,
            communication=request.communication.model_dump(),
            authored_notes=request.authored_notes,
            style_exemplars=request.style_exemplars,
            body_revision=request.body_revision,
            feedback=request.feedback,
        )
    except PersonalityAuthoringError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "blueprint_sha256": result["blueprint_sha256"],
        "candidate": result["candidate"],
        "audition_suite": result["audition_suite"],
        "saved_personality_revision": result["saved_personality_revision"],
        "profile": result["profile"],
    }


def run() -> None:
    import uvicorn

    host = os.environ.get("BODYRIG_HOST", DEFAULT_HOST)
    if host not in {"127.0.0.1", "localhost", "::1"} and os.environ.get("BODYRIG_ALLOW_REMOTE") != "1":
        raise SystemExit("BodyRig refuses non-loopback bind unless BODYRIG_ALLOW_REMOTE=1")
    port = int(os.environ.get("BODYRIG_PORT", str(DEFAULT_PORT)))
    uvicorn.run("bodyrig.guided_app:app", host=host, port=port, reload=False)
