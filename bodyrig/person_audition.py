from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .execution_provenance import consume_runtime_provenance

FORMAT = "bodyrig-person-audition"
VERSION = 1
PERSON_ID_RE = re.compile(r"^person-[0-9a-f]{32}$")
AUDITION_ID_RE = re.compile(r"^audition-[0-9a-f]{32}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PersonAuditionError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _root(root: str | os.PathLike[str], person_id: str) -> Path:
    if not PERSON_ID_RE.fullmatch(person_id):
        raise PersonAuditionError("person_id is invalid")
    return Path(root).expanduser().resolve() / "audition-receipts" / person_id


def receipt_path(root: str | os.PathLike[str], person_id: str, audition_id: str) -> Path:
    if not AUDITION_ID_RE.fullmatch(audition_id):
        raise PersonAuditionError("audition_id is invalid")
    return _root(root, person_id) / f"{audition_id}.json"


def audio_path(root: str | os.PathLike[str], person_id: str, audition_id: str) -> Path:
    if not AUDITION_ID_RE.fullmatch(audition_id):
        raise PersonAuditionError("audition_id is invalid")
    return _root(root, person_id) / f"{audition_id}.wav"


def _runtime_version(value: Any, *, field: str) -> str:
    if not isinstance(value, str):
        raise PersonAuditionError(f"{field} is invalid")
    text = value.strip()
    if not text or len(text) > 160 or any(ord(ch) < 32 for ch in text):
        raise PersonAuditionError(f"{field} is invalid")
    return text


def _validate(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    expected = {
        "format",
        "version",
        "audition_id",
        "person_id",
        "created_utc",
        "assembly_fingerprint",
        "modelrig_service",
        "modelrig_version",
        "model",
        "voicerig_service",
        "voicerig_version",
        "prompt_sha256",
        "reply_sha256",
        "audio_sha256",
        "complete",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise PersonAuditionError("audition receipt fields must match v1 exactly")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise PersonAuditionError("unsupported audition receipt format/version")
    audition_id = value.get("audition_id")
    person_id = value.get("person_id")
    if not isinstance(audition_id, str) or not AUDITION_ID_RE.fullmatch(audition_id):
        raise PersonAuditionError("audition_id is invalid")
    if not isinstance(person_id, str) or not PERSON_ID_RE.fullmatch(person_id):
        raise PersonAuditionError("person_id is invalid")
    created = value.get("created_utc")
    if not isinstance(created, str) or not created:
        raise PersonAuditionError("created_utc is invalid")
    try:
        parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PersonAuditionError("created_utc is invalid") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PersonAuditionError("created_utc must include timezone")
    if value.get("modelrig_service") != "modelrig-server":
        raise PersonAuditionError("modelrig_service must be modelrig-server")
    modelrig_version = _runtime_version(value.get("modelrig_version"), field="modelrig_version")
    model = value.get("model")
    if not isinstance(model, str) or not model.strip() or len(model) > 256 or any(ord(ch) < 32 for ch in model):
        raise PersonAuditionError("model is invalid")
    if value.get("voicerig_service") != "voicerig":
        raise PersonAuditionError("voicerig_service must be voicerig")
    voicerig_version = _runtime_version(value.get("voicerig_version"), field="voicerig_version")
    for field in ("assembly_fingerprint", "prompt_sha256", "reply_sha256", "audio_sha256"):
        item = value.get(field)
        if not isinstance(item, str) or not SHA256_RE.fullmatch(item):
            raise PersonAuditionError(f"{field} must be lowercase SHA-256")
    if value.get("complete") is not True:
        raise PersonAuditionError("audition receipt must be complete")
    result = dict(value)
    result["modelrig_version"] = modelrig_version
    result["voicerig_version"] = voicerig_version
    return result


def _resolve_runtime_provenance(
    *,
    modelrig_service: str | None,
    modelrig_version: str | None,
    voicerig_service: str | None,
    voicerig_version: str | None,
) -> tuple[str, str, str, str]:
    # Consume request-local provenance on every materialization attempt so a
    # failed/abandoned audition can never bleed runtime identity into the next one.
    observed = consume_runtime_provenance()
    explicit = (modelrig_service, modelrig_version, voicerig_service, voicerig_version)
    if any(item is not None for item in explicit):
        if not all(item is not None for item in explicit):
            raise PersonAuditionError("explicit audition runtime provenance is incomplete")
        mr_service = str(modelrig_service or "").strip()
        vr_service = str(voicerig_service or "").strip()
        mr_version = _runtime_version(modelrig_version, field="modelrig_version")
        vr_version = _runtime_version(voicerig_version, field="voicerig_version")
    else:
        mr_service = "modelrig-server"
        vr_service = "voicerig"
        mr_version = observed.get(mr_service, "")
        vr_version = observed.get(vr_service, "")
        if not mr_version or not vr_version:
            raise PersonAuditionError("audition execution runtime provenance is incomplete")
        mr_version = _runtime_version(mr_version, field="modelrig_version")
        vr_version = _runtime_version(vr_version, field="voicerig_version")

    if mr_service != "modelrig-server":
        raise PersonAuditionError("modelrig_service must be modelrig-server")
    if vr_service != "voicerig":
        raise PersonAuditionError("voicerig_service must be voicerig")
    return mr_service, mr_version, vr_service, vr_version


def write_audition(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    assembly_fingerprint: str,
    model: str,
    prompt: str,
    reply: str,
    audio: bytes,
    modelrig_service: str | None = None,
    modelrig_version: str | None = None,
    voicerig_service: str | None = None,
    voicerig_version: str | None = None,
) -> dict[str, Any]:
    if not isinstance(assembly_fingerprint, str) or not SHA256_RE.fullmatch(assembly_fingerprint):
        raise PersonAuditionError("assembly_fingerprint is invalid")
    mr_service, mr_version, vr_service, vr_version = _resolve_runtime_provenance(
        modelrig_service=modelrig_service,
        modelrig_version=modelrig_version,
        voicerig_service=voicerig_service,
        voicerig_version=voicerig_version,
    )
    model = str(model or "").strip()
    prompt = str(prompt or "").strip()
    reply = str(reply or "").strip()
    if not model or len(model) > 256 or any(ord(ch) < 32 for ch in model):
        raise PersonAuditionError("model is invalid")
    if not prompt or len(prompt) > 16_000:
        raise PersonAuditionError("prompt is invalid")
    if not reply or len(reply) > 64_000:
        raise PersonAuditionError("reply is invalid")
    if not isinstance(audio, bytes) or not audio.startswith(b"RIFF") or len(audio) < 44:
        raise PersonAuditionError("audition audio must be WAV bytes")

    audition_id = f"audition-{uuid.uuid4().hex}"
    payload = _validate({
        "format": FORMAT,
        "version": VERSION,
        "audition_id": audition_id,
        "person_id": person_id,
        "created_utc": _now(),
        "assembly_fingerprint": assembly_fingerprint,
        "modelrig_service": mr_service,
        "modelrig_version": mr_version,
        "model": model,
        "voicerig_service": vr_service,
        "voicerig_version": vr_version,
        "prompt_sha256": _sha256_text(prompt),
        "reply_sha256": _sha256_text(reply),
        "audio_sha256": _sha256_bytes(audio),
        "complete": True,
    })
    receipt = receipt_path(root, person_id, audition_id)
    wav = audio_path(root, person_id, audition_id)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    wrote_audio = False
    try:
        with wav.open("xb") as handle:
            handle.write(audio)
        wrote_audio = True
        with receipt.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
    except FileExistsError as exc:
        if wrote_audio:
            wav.unlink(missing_ok=True)
        raise PersonAuditionError("audition evidence already exists") from exc
    except Exception:
        if wrote_audio:
            wav.unlink(missing_ok=True)
        receipt.unlink(missing_ok=True)
        raise
    return payload


def read_audition(root: str | os.PathLike[str], *, person_id: str, audition_id: str) -> dict[str, Any]:
    receipt = receipt_path(root, person_id, audition_id)
    if not receipt.is_file():
        raise PersonAuditionError("audition receipt not found")
    try:
        value = json.loads(receipt.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonAuditionError("audition receipt is invalid JSON") from exc
    result = _validate(value)
    if result["person_id"] != person_id or result["audition_id"] != audition_id:
        raise PersonAuditionError("audition receipt identity mismatch")
    return result


def verify_audition(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    audition_id: str,
    assembly_fingerprint: str,
) -> dict[str, Any]:
    receipt = read_audition(root, person_id=person_id, audition_id=audition_id)
    if receipt["assembly_fingerprint"] != assembly_fingerprint:
        raise PersonAuditionError("audition was produced for a different person assembly")
    wav = audio_path(root, person_id, audition_id)
    if not wav.is_file() or _sha256_file(wav) != receipt["audio_sha256"]:
        raise PersonAuditionError("audition audio no longer matches its receipt")
    return receipt


def receipt_sha256(root: str | os.PathLike[str], *, person_id: str, audition_id: str) -> str:
    receipt = receipt_path(root, person_id, audition_id)
    if not receipt.is_file():
        raise PersonAuditionError("audition receipt not found")
    return _sha256_file(receipt)
