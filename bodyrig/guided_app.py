from __future__ import annotations

import os
from typing import Annotated, Any

from fastapi import HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from .app import DEFAULT_HOST, DEFAULT_PORT, app, person_library
from .personality_audition_suite import PersonalityAuditionSuiteError, build_audition_suite
from .personality_authoring import (
    PersonalityAuthoringError,
    build_guided_personality,
    save_guided_personality,
)
from .personality_source import SourcePersonalityError, build_source_personality
from .personality_suite_review import (
    PersonalitySuiteReviewError,
    seal_suite_review,
    suite_review_sha256,
    verify_suite_review,
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
    style_report: dict[str, Any] | None = None
    style_approval: dict[str, Any] | None = None
    body_revision: str | None = Field(default=None, max_length=24)


class GuidedPersonalitySaveRequest(GuidedPersonalityRequest):
    feedback: str = Field(default="", max_length=8000)


class PersonalitySuiteSealRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body_revision: str = Field(min_length=1, max_length=24)
    voice_revision: str = Field(min_length=1, max_length=24)
    personality_revision: str = Field(min_length=1, max_length=24)
    assembly_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    model: str = Field(min_length=1, max_length=256)
    default_language: str = Field(min_length=2, max_length=16)
    audition_ids: dict[str, str]


def _authoring_kwargs(request: GuidedPersonalityRequest) -> dict[str, Any]:
    return {
        "default_language": request.default_language,
        "communication": request.communication.model_dump(),
        "authored_notes": request.authored_notes,
        "style_exemplars": request.style_exemplars,
        "style_report": request.style_report,
        "style_approval": request.style_approval,
        "body_revision": request.body_revision,
    }


def _preview(person_id: str, request: GuidedPersonalityRequest) -> dict:
    try:
        return build_guided_personality(person_library(), person_id, **_authoring_kwargs(request))
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
            **_authoring_kwargs(request),
            feedback=request.feedback,
        )
    except PersonalityAuthoringError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "blueprint_sha256": result["blueprint_sha256"],
        "candidate": result["candidate"],
        "audition_suite": result["audition_suite"],
        "style_evidence": result["style_evidence"],
        "saved_personality_revision": result["saved_personality_revision"],
        "profile": result["profile"],
    }


@app.post("/api/v1/people/{person_id}/personality/build-from-source")
def source_personality_revision(
    person_id: str,
    body_revision: str = Query(min_length=1, max_length=24),
    language: str = Query(default="en", min_length=2, max_length=16),
) -> dict:
    try:
        return build_source_personality(
            person_library(),
            person_id,
            body_revision=body_revision,
            default_language=language,
        )
    except SourcePersonalityError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/personality/audition-suite")
def personality_audition_suite(language: str = "da") -> dict:
    try:
        return build_audition_suite(language)
    except PersonalityAuditionSuiteError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/people/{person_id}/personality/audition-suite/reviews")
def create_personality_suite_review(person_id: str, request: PersonalitySuiteSealRequest) -> dict:
    try:
        review = seal_suite_review(
            person_library(),
            person_id=person_id,
            body_revision=request.body_revision,
            voice_revision=request.voice_revision,
            personality_revision=request.personality_revision,
            assembly_fingerprint=request.assembly_fingerprint,
            model=request.model,
            default_language=request.default_language,
            audition_ids=request.audition_ids,
        )
        review_sha = suite_review_sha256(
            person_library(),
            person_id=person_id,
            review_id=review["review_id"],
        )
    except PersonalitySuiteReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"review": review, "review_sha256": review_sha}


@app.get("/api/v1/people/{person_id}/personality/audition-suite/reviews/{review_id}")
def get_personality_suite_review(person_id: str, review_id: str) -> dict:
    try:
        review = verify_suite_review(
            person_library(),
            person_id=person_id,
            review_id=review_id,
        )
        review_sha = suite_review_sha256(
            person_library(),
            person_id=person_id,
            review_id=review_id,
        )
    except PersonalitySuiteReviewError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"review": review, "review_sha256": review_sha}


def run() -> None:
    import uvicorn

    host = os.environ.get("BODYRIG_HOST", DEFAULT_HOST)
    if host not in {"127.0.0.1", "localhost", "::1"} and os.environ.get("BODYRIG_ALLOW_REMOTE") != "1":
        raise SystemExit("BodyRig refuses non-loopback bind unless BODYRIG_ALLOW_REMOTE=1")
    port = int(os.environ.get("BODYRIG_PORT", str(DEFAULT_PORT)))
    uvicorn.run("bodyrig.guided_app:app", host=host, port=port, reload=False)
