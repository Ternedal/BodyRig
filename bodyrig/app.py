from __future__ import annotations

import hashlib
import ipaddress
import os
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .body_feedback import propose_bodyprint_changes
from .models import BodyCue, SpeechTiming
from .package import MRBodyError, install_package, validate_package
from .person_profiles import (
    PersonProfileError,
    activate_person_revision,
    active_bundle,
    add_person_revision,
    add_personality_revision,
    add_voice_revision,
    create_profile,
    list_profiles,
    load_profile,
)
from .runtime import BodyRuntime
from .stash_source import StashClient, StashConfig, StashSourceError
from .storage import body_library as _body_library
from .storage import person_library as _person_library
from .ui_jobs import UiJobError, manager as ui_jobs, operator_checkout_status

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8775
runtime = BodyRuntime()
app = FastAPI(title="BodyRig", version=__version__)
UI_DIR = Path(__file__).resolve().parent / "ui"
app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")


def body_library() -> Path:
    return _body_library()


def person_library() -> Path:
    return _person_library()


def _is_loopback(host: str | None) -> bool:
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@app.middleware("http")
async def _loopback_only(request: Request, call_next):
    if os.environ.get("BODYRIG_ALLOW_REMOTE") != "1":
        peer = request.client.host if request.client else None
        if not _is_loopback(peer):
            return JSONResponse(
                status_code=403,
                content={
                    "detail": (
                        "BodyRig is loopback-only; set BODYRIG_ALLOW_REMOTE=1 only for an intentional remote deployment."
                    )
                },
            )
    return await call_next(request)


class ImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str = Field(min_length=1, max_length=4096)


class StashPerformerRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=160)
    name: str = Field(min_length=1, max_length=160)
    disambiguation: str = Field(default="", max_length=240)


class PersonCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str = Field(min_length=1, max_length=160)
    aliases: list[str] = Field(default_factory=list, max_length=50)
    stash_performer: StashPerformerRef | None = None


class PersonalityRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instructions: str = Field(min_length=1, max_length=64_000)
    default_language: str = Field(default="da", min_length=2, max_length=16)
    style_notes: str = Field(default="", max_length=16_000)
    feedback: str = Field(default="", max_length=8000)


class VoiceRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voice_id: str = Field(min_length=1, max_length=160)
    package_path: str | None = Field(default=None, max_length=4096)
    feedback: str = Field(default="", max_length=8000)


class PersonRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body_revision: str = Field(min_length=1, max_length=24)
    voice_revision: str = Field(min_length=1, max_length=24)
    personality_revision: str = Field(min_length=1, max_length=24)
    body_voice_match: bool
    voice_personality_match: bool
    body_personality_match: bool
    overall_coherent: bool
    compatibility_note: str = Field(min_length=1, max_length=8000)
    feedback: str = Field(default="", max_length=8000)
    activate: bool = True


class BodyProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback: str = Field(min_length=1, max_length=8000)


class BodyBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _stash_client() -> StashClient:
    url = os.environ.get("STASH_URL", "").strip()
    key = os.environ.get("STASH_API_KEY", "").strip()
    if not url:
        raise HTTPException(status_code=503, detail="STASH_URL is not configured in the BodyRig service environment.")
    if not key:
        raise HTTPException(status_code=503, detail="STASH_API_KEY is not configured in the BodyRig service environment.")
    try:
        return StashClient(StashConfig(url=url, api_key=key))
    except StashSourceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _revision(profile: dict[str, Any], kind: str, revision_id: str | None) -> dict[str, Any]:
    selected = revision_id
    if not selected:
        bundle = active_bundle(profile)
        if bundle is not None:
            selected = str(bundle[f"{kind}_revision"])
        elif profile[f"{kind}_revisions"]:
            selected = str(profile[f"{kind}_revisions"][-1]["revision_id"])
    if not selected:
        raise HTTPException(status_code=404, detail=f"No {kind} revision for this person.")
    for item in profile[f"{kind}_revisions"]:
        if item["revision_id"] == selected:
            return item
    raise HTTPException(status_code=404, detail=f"{kind} revision not found.")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(UI_DIR / "index.html", media_type="text/html")


@app.get("/api/v1/health")
def health() -> dict:
    authority = operator_checkout_status()
    return {
        "ok": True,
        "service": "bodyrig",
        "version": __version__,
        "people": len(list_profiles(person_library())),
        "physical_build_ready": bool(authority.get("ok")),
        "physical_build_reason": authority.get("reason"),
    }


@app.get("/api/v1/stash/health")
def stash_health() -> dict:
    client = _stash_client()
    try:
        version = client.version()
        client.search_performers("__bodyrig_capability_probe__", limit=1)
    except StashSourceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "version": version, "performer_read": True}


@app.get("/api/v1/stash/search")
def stash_search(q: str = Query(min_length=1, max_length=160), limit: int = Query(default=15, ge=1, le=100)) -> dict:
    client = _stash_client()
    try:
        version = client.version()
        performers = client.search_performers(q, limit=limit)
    except StashSourceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "version": version, "performers": performers}


@app.get("/api/v1/people")
def people() -> dict:
    return {"people": list_profiles(person_library())}


@app.post("/api/v1/people")
def create_person(request: PersonCreateRequest) -> dict:
    try:
        return create_profile(
            person_library(),
            display_name=request.display_name,
            aliases=request.aliases,
            stash_performer=request.stash_performer.model_dump() if request.stash_performer else None,
        )
    except PersonProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/v1/people/{person_id}")
def get_person(person_id: str) -> dict:
    try:
        return load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/people/{person_id}/personality/revisions")
def create_personality_revision(person_id: str, request: PersonalityRevisionRequest) -> dict:
    try:
        return add_personality_revision(
            person_library(),
            person_id,
            instructions=request.instructions,
            default_language=request.default_language,
            style_notes=request.style_notes,
            feedback=request.feedback,
        )
    except PersonProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/people/{person_id}/voice/revisions")
def create_voice_revision(person_id: str, request: VoiceRevisionRequest) -> dict:
    package_path = None
    package_hash = None
    if request.package_path:
        candidate = Path(request.package_path).expanduser().resolve()
        if not candidate.is_file() or candidate.suffix.lower() != ".mrvoice":
            raise HTTPException(status_code=422, detail="Voice package path must reference an existing .mrvoice file.")
        package_path = str(candidate)
        package_hash = _sha256(candidate)
    try:
        return add_voice_revision(
            person_library(),
            person_id,
            voice_id=request.voice_id,
            package_sha256=package_hash,
            package_path=package_path,
            feedback=request.feedback,
        )
    except PersonProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/people/{person_id}/revisions")
def create_person_revision(person_id: str, request: PersonRevisionRequest) -> dict:
    review = {
        "body_voice_match": request.body_voice_match,
        "voice_personality_match": request.voice_personality_match,
        "body_personality_match": request.body_personality_match,
        "overall_coherent": request.overall_coherent,
        "note": request.compatibility_note,
    }
    try:
        return add_person_revision(
            person_library(),
            person_id,
            body_revision=request.body_revision,
            voice_revision=request.voice_revision,
            personality_revision=request.personality_revision,
            compatibility_review=review,
            feedback=request.feedback,
            activate=request.activate,
        )
    except PersonProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/people/{person_id}/revisions/{revision_id}/activate")
def activate_bundle(person_id: str, revision_id: str) -> dict:
    try:
        return activate_person_revision(person_library(), person_id, revision_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/people/{person_id}/activate/{kind}/{revision_id}", include_in_schema=False)
def reject_component_activation(person_id: str, kind: str, revision_id: str) -> dict:
    del person_id, kind, revision_id
    raise HTTPException(
        status_code=409,
        detail="Body, voice and personality cannot be activated independently. Create or activate an approved person revision.",
    )


@app.post("/api/v1/people/{person_id}/body/propose")
def propose_body_revision(person_id: str, request: BodyProposalRequest) -> dict:
    try:
        load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    changes = [item.to_json() for item in propose_bodyprint_changes(request.feedback)]
    return {"person_id": person_id, "feedback": request.feedback, "changes": changes, "applied": False}


@app.post("/api/v1/people/{person_id}/body/build")
def start_body_build(person_id: str, request: BodyBuildRequest) -> dict:
    del request
    try:
        return ui_jobs.start_body_build(person_id)
    except (UiJobError, PersonProfileError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/jobs")
def list_ui_jobs(person_id: str | None = None) -> dict:
    return {"jobs": ui_jobs.list(person_id=person_id)}


@app.get("/api/v1/jobs/{job_id}")
def get_ui_job(job_id: str) -> dict:
    try:
        return ui_jobs.get(job_id)
    except UiJobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/v1/jobs/{job_id}/cancel")
def cancel_ui_job(job_id: str) -> dict:
    try:
        return ui_jobs.cancel(job_id)
    except UiJobError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/v1/people/{person_id}/body/preview")
def body_preview(person_id: str, revision: str | None = None):
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    item = _revision(profile, "body", revision)
    package = Path(item["package_path"]).expanduser().resolve()
    if not package.is_file():
        raise HTTPException(status_code=404, detail="Body package for revision is missing.")
    if _sha256(package) != item["package_sha256"]:
        raise HTTPException(status_code=409, detail="Body package bytes no longer match the registered revision.")
    try:
        validated = validate_package(package)
        if validated.manifest["id"] != item["body_id"]:
            raise MRBodyError("body id mismatch")
        with zipfile.ZipFile(package, "r") as archive:
            payload = archive.read("thumbnail.png")
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Body preview is invalid: {exc}") from exc
    return Response(content=payload, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/v1/people/{person_id}/body/avatar")
def body_avatar(person_id: str, revision: str | None = None):
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    item = _revision(profile, "body", revision)
    package = Path(item["package_path"]).expanduser().resolve()
    if not package.is_file() or _sha256(package) != item["package_sha256"]:
        raise HTTPException(status_code=409, detail="Body package is missing or changed.")
    try:
        validated = validate_package(package)
        if validated.manifest["id"] != item["body_id"]:
            raise MRBodyError("body id mismatch")
        with zipfile.ZipFile(package, "r") as archive:
            payload = archive.read("avatar.vrm")
    except (MRBodyError, OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Body avatar is invalid: {exc}") from exc
    return Response(content=payload, media_type="model/gltf-binary", headers={"Cache-Control": "no-store"})


@app.get("/api/v1/bodies")
def list_bodies() -> dict:
    library = body_library()
    bodies = []
    if library.exists():
        for path in sorted(library.glob("*.mrbody")):
            try:
                validated = validate_package(path)
            except MRBodyError:
                continue
            bodies.append({"id": validated.manifest["id"], "name": validated.manifest["name"], "path": str(path)})
    return {"bodies": bodies, "active_body_id": runtime.snapshot().active_body_id}


@app.post("/api/v1/bodies/import")
def import_body(request: ImportRequest) -> dict:
    try:
        target = install_package(request.path, body_library())
        validated = validate_package(target)
    except (MRBodyError, OSError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"installed": True, "id": validated.manifest["id"], "path": str(target)}


@app.post("/api/v1/bodies/{body_id}/activate")
def activate_body(body_id: str) -> dict:
    try:
        validated = validate_package(body_library() / f"{body_id}.mrbody")
    except (MRBodyError, OSError) as exc:
        raise HTTPException(status_code=404, detail="body not found or invalid") from exc
    return runtime.activate(validated.manifest["id"], validated.bodyprint).__dict__


@app.post("/api/v1/runtime/cue")
def apply_cue(cue: BodyCue) -> dict:
    try:
        return runtime.apply_cue(cue).__dict__
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/runtime/speech-timing")
def apply_speech_timing(timing: SpeechTiming) -> dict:
    try:
        return runtime.apply_speech(timing).__dict__
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/runtime/state")
def runtime_state() -> dict:
    return runtime.snapshot().__dict__


@app.get("/api/v1/runtime/motor-state")
def motor_state() -> dict:
    try:
        return runtime.motor_state()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def run() -> None:
    import uvicorn

    host = os.environ.get("BODYRIG_HOST", DEFAULT_HOST)
    if host not in {"127.0.0.1", "localhost", "::1"} and os.environ.get("BODYRIG_ALLOW_REMOTE") != "1":
        raise SystemExit("BodyRig refuses non-loopback bind unless BODYRIG_ALLOW_REMOTE=1")
    port = int(os.environ.get("BODYRIG_PORT", str(DEFAULT_PORT)))
    uvicorn.run("bodyrig.app:app", host=host, port=port, reload=False)
