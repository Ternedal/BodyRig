from __future__ import annotations

import hashlib
import ipaddress
import os
import threading
import zipfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import __version__
from .body_feedback import propose_bodyprint_changes
from .high_fidelity_preview_api import router as high_fidelity_preview_router
from .modelrig_client import ModelRigClient, ModelRigClientError, ModelRigConfig
from .models import BodyCue, SpeechTiming
from .package import MRBodyError, install_package, validate_package
from .person_assembly import (
    PersonAssemblyError,
    build_assembly,
    read_receipt,
    verify_receipt,
    write_receipt,
)
from .person_audition import (
    PersonAuditionError,
    audio_path as audition_audio_path,
    read_audition,
    receipt_sha256 as audition_receipt_sha256,
    verify_audition,
    write_audition,
)
from .person_body_review import PersonBodyReviewError, read_review, review_image_path
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
from .person_release_status import PersonReleaseStatusError, inspect_candidate_release_status
from .runtime import BodyRuntime
from .stash_source import StashClient, StashConfig, StashSourceError
from .storage import body_library as _body_library
from .storage import person_library as _person_library
from .ui_jobs import UiJobError, manager as ui_jobs, operator_checkout_status
from .voicerig_client import VoiceRigClient, VoiceRigClientError, VoiceRigConfig

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8775
runtime = BodyRuntime()
app = FastAPI(title="BodyRig", version=__version__)
app.include_router(high_fidelity_preview_router)
UI_DIR = Path(__file__).resolve().parent / "ui"
app.mount("/ui", StaticFiles(directory=str(UI_DIR)), name="ui")
_APPROVAL_LOCK = threading.Lock()


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
                    "detail": "BodyRig is loopback-only; set BODYRIG_ALLOW_REMOTE=1 only for an intentional remote deployment."
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
    voice_package: str = Field(min_length=1, max_length=255)
    feedback: str = Field(default="", max_length=8000)


class VoiceSynthesizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=1, max_length=24)
    text: str = Field(min_length=1, max_length=4000)


class PersonAssemblyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body_revision: str = Field(min_length=1, max_length=24)
    voice_revision: str = Field(min_length=1, max_length=24)
    personality_revision: str = Field(min_length=1, max_length=24)


class PersonAuditionRequest(PersonAssemblyRequest):
    model: str = Field(min_length=1, max_length=256)
    prompt: str = Field(min_length=1, max_length=16_000)


class PersonRevisionRequest(PersonAssemblyRequest):
    assembly_fingerprint: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    audition_id: str = Field(min_length=41, max_length=41, pattern=r"^audition-[0-9a-f]{32}$")
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


class BodyChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(min_length=1, max_length=80)
    delta: float
    reason: str = Field(min_length=1, max_length=240)


class BodyBuildRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    feedback: str = Field(default="", max_length=8000)
    changes: list[BodyChangeRequest] = Field(default_factory=list, max_length=7)


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


def _voicerig_client() -> VoiceRigClient:
    url = os.environ.get("VOICERIG_URL", "http://127.0.0.1:8765").strip()
    try:
        return VoiceRigClient(VoiceRigConfig(url=url))
    except VoiceRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _modelrig_client() -> ModelRigClient:
    url = os.environ.get("MODELRIG_URL", "http://127.0.0.1:8080").strip()
    token = os.environ.get("MODELRIG_TOKEN", "")
    try:
        return ModelRigClient(ModelRigConfig(url=url, token=token))
    except ModelRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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


def _body_bytes_match(item: dict[str, Any]) -> Path:
    package = Path(item["package_path"]).expanduser().resolve()
    if not package.is_file():
        raise HTTPException(status_code=404, detail="Body package for revision is missing.")
    if _sha256(package) != item["package_sha256"]:
        raise HTTPException(status_code=409, detail="Body package bytes no longer match the registered revision.")
    try:
        validated = validate_package(package)
    except (MRBodyError, OSError) as exc:
        raise HTTPException(status_code=422, detail=f"Body package is invalid: {exc}") from exc
    if validated.manifest["id"] != item["body_id"]:
        raise HTTPException(status_code=409, detail="Body package identity no longer matches the registered revision.")
    return package


def _voice_bytes_match(item: dict[str, Any], client: VoiceRigClient) -> None:
    try:
        raw = client.package_bytes(str(item["voice_package"]))
    except VoiceRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if _sha256_bytes(raw) != item["package_sha256"]:
        raise HTTPException(status_code=409, detail="VoiceRig package bytes no longer match the registered voice revision.")


def _validated_assembly(profile: dict[str, Any], request: PersonAssemblyRequest) -> dict[str, Any]:
    try:
        assembly = build_assembly(
            profile,
            body_revision=request.body_revision,
            voice_revision=request.voice_revision,
            personality_revision=request.personality_revision,
        )
    except PersonAssemblyError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    body = _revision(profile, "body", request.body_revision)
    voice = _revision(profile, "voice", request.voice_revision)
    _body_bytes_match(body)
    _voice_bytes_match(voice, _voicerig_client())
    return assembly


def _personality_system_prompt(item: dict[str, Any]) -> str:
    parts = [str(item["instructions"]).strip()]
    style = str(item.get("style_notes") or "").strip()
    if style:
        parts.append(f"Style notes:\n{style}")
    parts.append(
        f"Default language: {item['default_language']}. Reply in this language unless the user explicitly asks for another language."
    )
    return "\n\n".join(parts)


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(UI_DIR / "person.html", media_type="text/html")


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


@app.get("/api/v1/voicerig/health")
def voicerig_health() -> dict:
    try:
        value = _voicerig_client().health()
    except VoiceRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "service": "voicerig", "version": value.get("version")}


@app.get("/api/v1/voicerig/voices")
def voicerig_voices() -> dict:
    try:
        voices = _voicerig_client().voices()
    except VoiceRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "voices": voices}


@app.get("/api/v1/modelrig/health")
def modelrig_health() -> dict:
    client = _modelrig_client()
    try:
        value = client.health()
    except ModelRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "service": value.get("service"), "version": value.get("version")}


@app.get("/api/v1/modelrig/models")
def modelrig_models() -> dict:
    client = _modelrig_client()
    try:
        client.health()
        models = client.models()
    except ModelRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"ok": True, "models": models}


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
    client = _voicerig_client()
    try:
        voices = client.voices()
        selected = next((item for item in voices if item["package"] == request.voice_package), None)
        if selected is None:
            raise VoiceRigClientError("The selected VoiceRig package is not present in VoiceRig's validated library")
        package_raw = client.package_bytes(request.voice_package)
    except VoiceRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    try:
        return add_voice_revision(
            person_library(),
            person_id,
            voice_id=str(selected["id"]),
            voice_package=str(selected["package"]),
            package_sha256=_sha256_bytes(package_raw),
            feedback=request.feedback,
        )
    except PersonProfileError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/people/{person_id}/voice/build-from-source")
def start_source_voice_build(
    person_id: str,
    body_revision: str = Query(min_length=1, max_length=24),
    language: str = Query(default="da", min_length=2, max_length=32),
) -> dict:
    try:
        return ui_jobs.start_voice_build(person_id, body_revision=body_revision, language=language)
    except (UiJobError, PersonProfileError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/people/{person_id}/voice/preview")
def voice_preview(person_id: str, revision: str | None = None):
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    item = _revision(profile, "voice", revision)
    client = _voicerig_client()
    _voice_bytes_match(item, client)
    try:
        raw = client.preview(str(item["voice_package"]))
    except VoiceRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=raw, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/v1/people/{person_id}/voice/synthesize")
def voice_synthesize(person_id: str, request: VoiceSynthesizeRequest):
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    item = _revision(profile, "voice", request.revision)
    client = _voicerig_client()
    _voice_bytes_match(item, client)
    try:
        raw = client.synthesize(str(item["voice_package"]), request.text)
    except VoiceRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=raw, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/v1/people/{person_id}/assembly")
def prepare_person_assembly(person_id: str, request: PersonAssemblyRequest) -> dict:
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assembly = _validated_assembly(profile, request)
    return {
        **assembly,
        "body_preview_url": f"/api/v1/people/{person_id}/body/preview?revision={request.body_revision}",
        "voice_preview_url": f"/api/v1/people/{person_id}/voice/preview?revision={request.voice_revision}",
        "voice_synthesize_url": f"/api/v1/people/{person_id}/voice/synthesize",
    }


@app.post("/api/v1/people/{person_id}/auditions")
def create_person_audition(person_id: str, request: PersonAuditionRequest) -> dict:
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    assembly = _validated_assembly(profile, request)
    personality = _revision(profile, "personality", request.personality_revision)
    voice = _revision(profile, "voice", request.voice_revision)

    modelrig = _modelrig_client()
    try:
        modelrig.health()
        reply = modelrig.chat(
            model=request.model,
            system=_personality_system_prompt(personality),
            prompt=request.prompt,
        )
    except ModelRigClientError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    voicerig = _voicerig_client()
    _voice_bytes_match(voice, voicerig)
    try:
        audio = voicerig.synthesize(str(voice["voice_package"]), reply)
        audition = write_audition(
            person_library(),
            person_id=person_id,
            assembly_fingerprint=str(assembly["assembly_fingerprint"]),
            model=request.model,
            prompt=request.prompt,
            reply=reply,
            audio=audio,
        )
    except (VoiceRigClientError, PersonAuditionError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {
        "ok": True,
        "audition_id": audition["audition_id"],
        "assembly_fingerprint": assembly["assembly_fingerprint"],
        "model": audition["model"],
        "reply": reply,
        "audio_url": f"/api/v1/people/{person_id}/auditions/{audition['audition_id']}/audio",
    }


@app.get("/api/v1/people/{person_id}/auditions/{audition_id}/audio")
def person_audition_audio(person_id: str, audition_id: str):
    try:
        receipt = read_audition(person_library(), person_id=person_id, audition_id=audition_id)
        verify_audition(
            person_library(),
            person_id=person_id,
            audition_id=audition_id,
            assembly_fingerprint=str(receipt["assembly_fingerprint"]),
        )
        payload = audition_audio_path(person_library(), person_id, audition_id).read_bytes()
    except (PersonAuditionError, OSError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(content=payload, media_type="audio/wav", headers={"Cache-Control": "no-store"})


@app.post("/api/v1/people/{person_id}/revisions")
def create_person_revision(person_id: str, request: PersonRevisionRequest) -> dict:
    review = {
        "body_voice_match": request.body_voice_match,
        "voice_personality_match": request.voice_personality_match,
        "body_personality_match": request.body_personality_match,
        "overall_coherent": request.overall_coherent,
        "note": request.compatibility_note,
    }
    with _APPROVAL_LOCK:
        try:
            profile = load_profile(person_library(), person_id)
        except PersonProfileError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        assembly = _validated_assembly(profile, request)
        if assembly["assembly_fingerprint"] != request.assembly_fingerprint:
            raise HTTPException(status_code=409, detail="The selected person assembly changed after audition. Audition it again before approval.")
        try:
            verify_audition(
                person_library(),
                person_id=person_id,
                audition_id=request.audition_id,
                assembly_fingerprint=request.assembly_fingerprint,
            )
            audition_sha = audition_receipt_sha256(
                person_library(),
                person_id=person_id,
                audition_id=request.audition_id,
            )
        except PersonAuditionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        try:
            profile = add_person_revision(
                person_library(),
                person_id,
                body_revision=request.body_revision,
                voice_revision=request.voice_revision,
                personality_revision=request.personality_revision,
                compatibility_review=review,
                feedback=request.feedback,
                activate=False,
            )
            person_revision = profile["person_revisions"][-1]["revision_id"]
            write_receipt(
                person_library(),
                person_revision=person_revision,
                assembly=assembly,
                audition_id=request.audition_id,
                audition_receipt_sha256=audition_sha,
            )
            if request.activate:
                profile = activate_person_revision(person_library(), person_id, person_revision)
            return profile
        except (PersonProfileError, PersonAssemblyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/v1/people/{person_id}/revisions/{revision_id}/activate")
def activate_bundle(person_id: str, revision_id: str) -> dict:
    with _APPROVAL_LOCK:
        try:
            profile = load_profile(person_library(), person_id)
        except PersonProfileError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        item = next((value for value in profile["person_revisions"] if value["revision_id"] == revision_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail="Unknown approved person revision.")
        request = PersonAssemblyRequest(
            body_revision=item["body_revision"],
            voice_revision=item["voice_revision"],
            personality_revision=item["personality_revision"],
        )
        assembly = _validated_assembly(profile, request)
        try:
            receipt = read_receipt(person_library(), person_id=person_id, person_revision=revision_id)
            audition_ref = receipt.get("audition")
            if not isinstance(audition_ref, dict):
                raise PersonAssemblyError("legacy person revision has no audition binding; audition it again before activation")
            audition_id = str(audition_ref.get("audition_id") or "")
            expected_sha = str(audition_ref.get("receipt_sha256") or "")
            verify_audition(
                person_library(),
                person_id=person_id,
                audition_id=audition_id,
                assembly_fingerprint=str(assembly["assembly_fingerprint"]),
            )
            actual_sha = audition_receipt_sha256(
                person_library(),
                person_id=person_id,
                audition_id=audition_id,
            )
            if actual_sha != expected_sha:
                raise PersonAuditionError("audition receipt no longer matches the approved Person Revision")
            verify_receipt(
                person_library(),
                person_revision=revision_id,
                assembly=assembly,
                audition_id=audition_id,
                audition_receipt_sha256=actual_sha,
            )
            return activate_person_revision(person_library(), person_id, revision_id)
        except (PersonAssemblyError, PersonAuditionError, PersonProfileError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    return {
        "person_id": person_id,
        "feedback": request.feedback,
        "changes": changes,
        "applied": False,
        "buildable": bool(changes),
    }


@app.post("/api/v1/people/{person_id}/body/build")
def start_body_build(person_id: str, request: BodyBuildRequest) -> dict:
    try:
        return ui_jobs.start_body_build(
            person_id,
            feedback=request.feedback,
            changes=[item.model_dump() for item in request.changes] if request.changes else None,
        )
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


@app.post("/api/v1/jobs/{job_id}/speaker")
def choose_ui_voice_speaker(job_id: str, anchor: str = Query(min_length=3, max_length=64)) -> dict:
    try:
        return ui_jobs.choose_voice_speaker(job_id, anchor)
    except UiJobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/v1/jobs/{job_id}/reference")
def choose_ui_voice_reference(job_id: str, choice: int = Query(ge=1, le=4)) -> dict:
    try:
        return ui_jobs.choose_voice_reference(job_id, choice)
    except UiJobError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    package = _body_bytes_match(item)
    try:
        with zipfile.ZipFile(package, "r") as archive:
            payload = archive.read("thumbnail.png")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise HTTPException(status_code=422, detail=f"Body preview is invalid: {exc}") from exc
    return Response(content=payload, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/v1/people/{person_id}/body/review")
def body_review(person_id: str, revision: str | None = None) -> dict:
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    item = _revision(profile, "body", revision)
    _body_bytes_match(item)
    try:
        review = read_review(person_library(), profile, body_revision=str(item["revision_id"]))
    except PersonBodyReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "person_id": person_id,
        "body_revision": item["revision_id"],
        "body_id": review["body_id"],
        "package_sha256": review["package_sha256"],
        "bodyrig_revision": review["bodyrig_revision"],
        "semantics": review["semantics"],
        "views": [
            {
                "view": view["view"],
                "sha256": view["sha256"],
                "width": view["width"],
                "height": view["height"],
                "url": f"/api/v1/people/{person_id}/body/review/{view['view']}?revision={item['revision_id']}",
            }
            for view in review["views"]
        ],
    }


@app.get("/api/v1/people/{person_id}/body/release-status")
def body_release_status(person_id: str, revision: str | None = None) -> dict:
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    item = _revision(profile, "body", revision)
    _body_bytes_match(item)
    try:
        return inspect_candidate_release_status(
            ui_jobs.list(person_id=person_id),
            person_id=person_id,
            body_revision=str(item["revision_id"]),
            body_id=str(item["body_id"]),
            package_sha256=str(item["package_sha256"]),
        )
    except PersonReleaseStatusError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/v1/people/{person_id}/body/review/{view}")
def body_review_image(person_id: str, view: str, revision: str | None = None):
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    item = _revision(profile, "body", revision)
    _body_bytes_match(item)
    try:
        path = review_image_path(
            person_library(),
            profile,
            body_revision=str(item["revision_id"]),
            view=view,
        )
    except PersonBodyReviewError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/api/v1/people/{person_id}/body/avatar")
def body_avatar(person_id: str, revision: str | None = None):
    try:
        profile = load_profile(person_library(), person_id)
    except PersonProfileError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    item = _revision(profile, "body", revision)
    package = _body_bytes_match(item)
    try:
        with zipfile.ZipFile(package, "r") as archive:
            payload = archive.read("avatar.vrm")
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
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


@app.get("/api/v2/runtime/motor-state")
def motor_state_v2() -> dict:
    try:
        return runtime.motor_state_v2()
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def run() -> None:
    import uvicorn

    host = os.environ.get("BODYRIG_HOST", DEFAULT_HOST)
    if host not in {"127.0.0.1", "localhost", "::1"} and os.environ.get("BODYRIG_ALLOW_REMOTE") != "1":
        raise SystemExit("BodyRig refuses non-loopback bind unless BODYRIG_ALLOW_REMOTE=1")
    port = int(os.environ.get("BODYRIG_PORT", str(DEFAULT_PORT)))
    uvicorn.run("bodyrig.app:app", host=host, port=port, reload=False)