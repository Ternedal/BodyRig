from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .person_source_alignment import PersonSourceAlignmentError, read_binding, require_alignment

FORMAT = "modelrig-person-profile"
VERSION = 1
PERSON_ID_RE = re.compile(r"^person-[0-9a-f]{32}$")
BODY_ID_RE = re.compile(r"^[a-z0-9æøå_-]{1,160}$")
VOICE_ID_RE = BODY_ID_RE
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMPONENT_REVISION_RE = re.compile(r"^(body|voice|personality)-r[0-9]{4}$")
PERSON_REVISION_RE = re.compile(r"^person-r[0-9]{4}$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})?$")

TOP_FIELDS = {
    "format",
    "version",
    "person_id",
    "display_name",
    "aliases",
    "created_utc",
    "updated_utc",
    "source",
    "active_person_revision",
    "body_revisions",
    "voice_revisions",
    "personality_revisions",
    "person_revisions",
}
SOURCE_FIELDS = {"kind", "performer_id", "performer_name", "disambiguation"}
BODY_FIELDS = {
    "revision_id",
    "created_utc",
    "body_id",
    "package_sha256",
    "package_path",
    "preview_path",
    "feedback",
}
VOICE_FIELDS = {
    "revision_id",
    "created_utc",
    "voice_id",
    "voice_package",
    "package_sha256",
    "feedback",
}
PERSONALITY_FIELDS = {
    "revision_id",
    "created_utc",
    "instructions",
    "default_language",
    "style_notes",
    "feedback",
}
PERSON_REVISION_FIELDS = {
    "revision_id",
    "created_utc",
    "body_revision",
    "voice_revision",
    "personality_revision",
    "compatibility_review",
    "feedback",
}
COMPATIBILITY_FIELDS = {
    "body_voice_match",
    "voice_personality_match",
    "body_personality_match",
    "overall_coherent",
    "note",
}


class PersonProfileError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _text(value: Any, *, field: str, maximum: int, empty: bool = False) -> str:
    if not isinstance(value, str):
        raise PersonProfileError(f"{field} must be text")
    cleaned = value.strip()
    if (not empty and not cleaned) or len(cleaned) > maximum or any(ord(ch) < 32 and ch not in "\n\t" for ch in cleaned):
        raise PersonProfileError(f"{field} is invalid")
    return cleaned


def _nullable_text(value: Any, *, field: str, maximum: int) -> str | None:
    if value is None:
        return None
    return _text(value, field=field, maximum=maximum)


def _timestamp(value: Any, *, field: str) -> str:
    text = _text(value, field=field, maximum=80)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PersonProfileError(f"{field} must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PersonProfileError(f"{field} must include timezone")
    return text


def _sha(value: Any, *, field: str, nullable: bool = False) -> str | None:
    if value is None and nullable:
        return None
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise PersonProfileError(f"{field} must be lowercase SHA-256")
    return value


def _voice_package(value: Any) -> str:
    package = _text(value, field="voice_package", maximum=255)
    if "/" in package or "\\" in package or package in {".", ".."} or not package.lower().endswith(".mrvoice"):
        raise PersonProfileError("voice_package must be a safe .mrvoice filename")
    return package


def _component_revision_id(value: Any, *, kind: str) -> str:
    text = _text(value, field="revision_id", maximum=24)
    if not COMPONENT_REVISION_RE.fullmatch(text) or not text.startswith(f"{kind}-r"):
        raise PersonProfileError(f"invalid {kind} revision id")
    return text


def _person_revision_id(value: Any) -> str:
    text = _text(value, field="person revision_id", maximum=24)
    if not PERSON_REVISION_RE.fullmatch(text):
        raise PersonProfileError("invalid person revision id")
    return text


def _validate_source(value: Any) -> dict[str, str] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != SOURCE_FIELDS or value.get("kind") != "stash-performer":
        raise PersonProfileError("source must be null or an exact stash-performer binding")
    return {
        "kind": "stash-performer",
        "performer_id": _text(value["performer_id"], field="source.performer_id", maximum=160),
        "performer_name": _text(value["performer_name"], field="source.performer_name", maximum=160),
        "disambiguation": _text(value["disambiguation"], field="source.disambiguation", maximum=240, empty=True),
    }


def _validate_body_revision(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != BODY_FIELDS:
        raise PersonProfileError("body revision fields must match v1 exactly")
    body_id = _text(value["body_id"], field="body_id", maximum=160)
    if not BODY_ID_RE.fullmatch(body_id):
        raise PersonProfileError("body_id is invalid")
    return {
        "revision_id": _component_revision_id(value["revision_id"], kind="body"),
        "created_utc": _timestamp(value["created_utc"], field="created_utc"),
        "body_id": body_id,
        "package_sha256": _sha(value["package_sha256"], field="package_sha256"),
        "package_path": _text(value["package_path"], field="package_path", maximum=4096),
        "preview_path": _nullable_text(value["preview_path"], field="preview_path", maximum=4096),
        "feedback": _text(value["feedback"], field="feedback", maximum=8000, empty=True),
    }


def _validate_voice_revision(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != VOICE_FIELDS:
        raise PersonProfileError("voice revision fields must match v1 exactly")
    voice_id = _text(value["voice_id"], field="voice_id", maximum=160)
    if not VOICE_ID_RE.fullmatch(voice_id):
        raise PersonProfileError("voice_id is invalid")
    return {
        "revision_id": _component_revision_id(value["revision_id"], kind="voice"),
        "created_utc": _timestamp(value["created_utc"], field="created_utc"),
        "voice_id": voice_id,
        "voice_package": _voice_package(value["voice_package"]),
        "package_sha256": _sha(value["package_sha256"], field="package_sha256"),
        "feedback": _text(value["feedback"], field="feedback", maximum=8000, empty=True),
    }


def _validate_personality_revision(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != PERSONALITY_FIELDS:
        raise PersonProfileError("personality revision fields must match v1 exactly")
    language = _text(value["default_language"], field="default_language", maximum=16)
    if not LANGUAGE_RE.fullmatch(language):
        raise PersonProfileError("default_language is invalid")
    return {
        "revision_id": _component_revision_id(value["revision_id"], kind="personality"),
        "created_utc": _timestamp(value["created_utc"], field="created_utc"),
        "instructions": _text(value["instructions"], field="instructions", maximum=64_000),
        "default_language": language,
        "style_notes": _text(value["style_notes"], field="style_notes", maximum=16_000, empty=True),
        "feedback": _text(value["feedback"], field="feedback", maximum=8000, empty=True),
    }


def _validate_compatibility(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != COMPATIBILITY_FIELDS:
        raise PersonProfileError("compatibility review fields must match v1 exactly")
    result: dict[str, Any] = {}
    for field in ("body_voice_match", "voice_personality_match", "body_personality_match", "overall_coherent"):
        if value[field] is not True:
            raise PersonProfileError(f"compatibility.{field} must be explicitly true")
        result[field] = True
    result["note"] = _text(value["note"], field="compatibility.note", maximum=8000)
    return result


def _validate_person_revision(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != PERSON_REVISION_FIELDS:
        raise PersonProfileError("person revision fields must match v1 exactly")
    return {
        "revision_id": _person_revision_id(value["revision_id"]),
        "created_utc": _timestamp(value["created_utc"], field="created_utc"),
        "body_revision": _component_revision_id(value["body_revision"], kind="body"),
        "voice_revision": _component_revision_id(value["voice_revision"], kind="voice"),
        "personality_revision": _component_revision_id(value["personality_revision"], kind="personality"),
        "compatibility_review": _validate_compatibility(value["compatibility_review"]),
        "feedback": _text(value["feedback"], field="feedback", maximum=8000, empty=True),
    }


def validate_profile(value: Mapping[str, Any] | Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != TOP_FIELDS:
        raise PersonProfileError("person profile fields must match v1 exactly")
    if value.get("format") != FORMAT or value.get("version") != VERSION:
        raise PersonProfileError("unsupported person profile format/version")
    person_id = value.get("person_id")
    if not isinstance(person_id, str) or not PERSON_ID_RE.fullmatch(person_id):
        raise PersonProfileError("person_id is invalid")

    aliases = value.get("aliases")
    if not isinstance(aliases, list) or len(aliases) > 50:
        raise PersonProfileError("aliases must be a list with at most 50 items")
    clean_aliases: list[str] = []
    seen: set[str] = set()
    for alias in aliases:
        clean = _text(alias, field="alias", maximum=160)
        key = clean.casefold()
        if key in seen:
            raise PersonProfileError("aliases must be unique")
        seen.add(key)
        clean_aliases.append(clean)

    raw_body = value.get("body_revisions")
    raw_voice = value.get("voice_revisions")
    raw_personality = value.get("personality_revisions")
    raw_person = value.get("person_revisions")
    if not all(isinstance(items, list) for items in (raw_body, raw_voice, raw_personality, raw_person)):
        raise PersonProfileError("revision collections must be lists")
    body_revisions = [_validate_body_revision(item) for item in raw_body]
    voice_revisions = [_validate_voice_revision(item) for item in raw_voice]
    personality_revisions = [_validate_personality_revision(item) for item in raw_personality]
    person_revisions = [_validate_person_revision(item) for item in raw_person]

    def _ids(items: list[dict[str, Any]], kind: str) -> set[str]:
        ids = [item["revision_id"] for item in items]
        if len(ids) != len(set(ids)):
            raise PersonProfileError(f"duplicate {kind} revision id")
        return set(ids)

    body_ids = _ids(body_revisions, "body")
    voice_ids = _ids(voice_revisions, "voice")
    personality_ids = _ids(personality_revisions, "personality")
    person_ids = _ids(person_revisions, "person")
    for item in person_revisions:
        if item["body_revision"] not in body_ids:
            raise PersonProfileError("person revision references unknown body revision")
        if item["voice_revision"] not in voice_ids:
            raise PersonProfileError("person revision references unknown voice revision")
        if item["personality_revision"] not in personality_ids:
            raise PersonProfileError("person revision references unknown personality revision")

    active = value.get("active_person_revision")
    if active is not None and (not isinstance(active, str) or active not in person_ids):
        raise PersonProfileError("active_person_revision does not reference an existing approved person revision")

    return {
        "format": FORMAT,
        "version": VERSION,
        "person_id": person_id,
        "display_name": _text(value["display_name"], field="display_name", maximum=160),
        "aliases": clean_aliases,
        "created_utc": _timestamp(value["created_utc"], field="created_utc"),
        "updated_utc": _timestamp(value["updated_utc"], field="updated_utc"),
        "source": _validate_source(value["source"]),
        "active_person_revision": active,
        "body_revisions": body_revisions,
        "voice_revisions": voice_revisions,
        "personality_revisions": personality_revisions,
        "person_revisions": person_revisions,
    }


def active_bundle(profile: Mapping[str, Any]) -> dict[str, Any] | None:
    revision_id = profile.get("active_person_revision")
    if not revision_id:
        return None
    for item in profile.get("person_revisions", []):
        if item.get("revision_id") == revision_id:
            return dict(item)
    raise PersonProfileError("active person revision is missing")


def _source_alignment_snapshot(root: str | os.PathLike[str], profile: Mapping[str, Any]) -> dict[str, Any] | None:
    source = profile.get("source")
    if not isinstance(source, Mapping):
        return None
    components: dict[str, dict[str, Any]] = {}
    aligned_revisions = 0
    blocked_revisions = 0
    for kind in ("body", "voice", "personality"):
        statuses: dict[str, Any] = {}
        for item in profile.get(f"{kind}_revisions", []):
            if not isinstance(item, Mapping):
                continue
            revision_id = str(item.get("revision_id") or "")
            try:
                receipt = read_binding(root, profile, kind=kind, revision_id=revision_id)
                statuses[revision_id] = {
                    "aligned": True,
                    "evidence_kind": receipt["evidence"]["kind"],
                    "evidence_sha256": receipt["evidence"]["sha256"],
                }
                aligned_revisions += 1
            except PersonSourceAlignmentError as exc:
                statuses[revision_id] = {"aligned": False, "reason": str(exc)}
                blocked_revisions += 1
        components[kind] = statuses
    return {
        "required": True,
        "source": dict(source),
        "components": components,
        "aligned_revisions": aligned_revisions,
        "blocked_revisions": blocked_revisions,
    }


def _path(root: Path, person_id: str) -> Path:
    if not PERSON_ID_RE.fullmatch(person_id):
        raise PersonProfileError("person_id is invalid")
    return root / f"{person_id}.json"


def _write_create(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise PersonProfileError(f"person profile already exists: {path.name}") from exc


def _write_replace(path: Path, value: Mapping[str, Any]) -> None:
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex}")
    try:
        temp.write_text(payload, encoding="utf-8", newline="\n")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_profile(root: str | os.PathLike[str], person_id: str) -> dict[str, Any]:
    directory = Path(root).expanduser().resolve()
    path = _path(directory, person_id)
    if not path.is_file():
        raise PersonProfileError(f"person profile not found: {person_id}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"), parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PersonProfileError(f"person profile is invalid JSON: {person_id}") from exc
    profile = validate_profile(value)
    alignment = _source_alignment_snapshot(directory, profile)
    if alignment is not None:
        profile["_source_alignment"] = alignment
    return profile


def list_profiles(root: str | os.PathLike[str]) -> list[dict[str, Any]]:
    directory = Path(root).expanduser().resolve()
    if not directory.exists():
        return []
    profiles: list[dict[str, Any]] = []
    for path in sorted(directory.glob("person-*.json")):
        try:
            profiles.append(load_profile(directory, path.stem))
        except PersonProfileError:
            continue
    return sorted(profiles, key=lambda item: (item["display_name"].casefold(), item["person_id"]))


def create_profile(root: str | os.PathLike[str], *, display_name: str, aliases: list[str] | None = None, stash_performer: Mapping[str, Any] | None = None) -> dict[str, Any]:
    now = _utc_now()
    source = None
    if stash_performer is not None:
        source = {
            "kind": "stash-performer",
            "performer_id": str(stash_performer.get("id") or ""),
            "performer_name": str(stash_performer.get("name") or ""),
            "disambiguation": str(stash_performer.get("disambiguation") or ""),
        }
    value = validate_profile({
        "format": FORMAT,
        "version": VERSION,
        "person_id": f"person-{uuid.uuid4().hex}",
        "display_name": display_name,
        "aliases": list(aliases or []),
        "created_utc": now,
        "updated_utc": now,
        "source": source,
        "active_person_revision": None,
        "body_revisions": [],
        "voice_revisions": [],
        "personality_revisions": [],
        "person_revisions": [],
    })
    _write_create(_path(Path(root).expanduser().resolve(), value["person_id"]), value)
    return value


def _next_revision(profile: Mapping[str, Any], kind: str) -> str:
    collection = profile["person_revisions"] if kind == "person" else profile[f"{kind}_revisions"]
    return f"{kind}-r{len(collection) + 1:04d}"


def _save(root: str | os.PathLike[str], profile: Mapping[str, Any]) -> dict[str, Any]:
    value = {field: profile[field] for field in TOP_FIELDS if field in profile}
    value["updated_utc"] = _utc_now()
    value = validate_profile(value)
    path = _path(Path(root).expanduser().resolve(), value["person_id"])
    if not path.is_file():
        raise PersonProfileError(f"person profile not found: {value['person_id']}")
    _write_replace(path, value)
    return value


def add_body_revision(root: str | os.PathLike[str], person_id: str, *, body_id: str, package_sha256: str, package_path: str, preview_path: str | None = None, feedback: str = "", activate: bool = False) -> dict[str, Any]:
    if activate:
        raise PersonProfileError("body revisions cannot be activated independently; create an approved person revision")
    profile = load_profile(root, person_id)
    revision = _validate_body_revision({
        "revision_id": _next_revision(profile, "body"),
        "created_utc": _utc_now(),
        "body_id": body_id,
        "package_sha256": package_sha256,
        "package_path": package_path,
        "preview_path": preview_path,
        "feedback": feedback,
    })
    profile["body_revisions"].append(revision)
    return _save(root, profile)


def add_voice_revision(root: str | os.PathLike[str], person_id: str, *, voice_id: str, voice_package: str, package_sha256: str, feedback: str = "", activate: bool = False) -> dict[str, Any]:
    if activate:
        raise PersonProfileError("voice revisions cannot be activated independently; create an approved person revision")
    profile = load_profile(root, person_id)
    revision = _validate_voice_revision({
        "revision_id": _next_revision(profile, "voice"),
        "created_utc": _utc_now(),
        "voice_id": voice_id,
        "voice_package": voice_package,
        "package_sha256": package_sha256,
        "feedback": feedback,
    })
    profile["voice_revisions"].append(revision)
    saved = _save(root, profile)
    return load_profile(root, person_id) if saved.get("source") is not None else saved


def add_personality_revision(root: str | os.PathLike[str], person_id: str, *, instructions: str, default_language: str = "da", style_notes: str = "", feedback: str = "", activate: bool = False) -> dict[str, Any]:
    if activate:
        raise PersonProfileError("personality revisions cannot be activated independently; create an approved person revision")
    profile = load_profile(root, person_id)
    revision = _validate_personality_revision({
        "revision_id": _next_revision(profile, "personality"),
        "created_utc": _utc_now(),
        "instructions": instructions,
        "default_language": default_language,
        "style_notes": style_notes,
        "feedback": feedback,
    })
    profile["personality_revisions"].append(revision)
    saved = _save(root, profile)
    return load_profile(root, person_id) if saved.get("source") is not None else saved


def add_person_revision(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    body_revision: str,
    voice_revision: str,
    personality_revision: str,
    compatibility_review: Mapping[str, Any],
    feedback: str = "",
    activate: bool = True,
) -> dict[str, Any]:
    profile = load_profile(root, person_id)
    revision = _validate_person_revision({
        "revision_id": _next_revision(profile, "person"),
        "created_utc": _utc_now(),
        "body_revision": body_revision,
        "voice_revision": voice_revision,
        "personality_revision": personality_revision,
        "compatibility_review": compatibility_review,
        "feedback": feedback,
    })
    body_ids = {item["revision_id"] for item in profile["body_revisions"]}
    voice_ids = {item["revision_id"] for item in profile["voice_revisions"]}
    personality_ids = {item["revision_id"] for item in profile["personality_revisions"]}
    if revision["body_revision"] not in body_ids or revision["voice_revision"] not in voice_ids or revision["personality_revision"] not in personality_ids:
        raise PersonProfileError("person revision must reference existing body, voice and personality revisions")
    if profile.get("source") is not None:
        try:
            require_alignment(
                root,
                profile,
                body_revision=revision["body_revision"],
                voice_revision=revision["voice_revision"],
                personality_revision=revision["personality_revision"],
            )
        except PersonSourceAlignmentError as exc:
            raise PersonProfileError(f"person source alignment failed: {exc}") from exc
    profile["person_revisions"].append(revision)
    if activate:
        profile["active_person_revision"] = revision["revision_id"]
    saved = _save(root, profile)
    return load_profile(root, person_id) if saved.get("source") is not None else saved


def activate_person_revision(root: str | os.PathLike[str], person_id: str, revision_id: str) -> dict[str, Any]:
    profile = load_profile(root, person_id)
    selected = next((item for item in profile["person_revisions"] if item["revision_id"] == revision_id), None)
    if selected is None:
        raise PersonProfileError("unknown approved person revision")
    if profile.get("source") is not None:
        try:
            require_alignment(
                root,
                profile,
                body_revision=selected["body_revision"],
                voice_revision=selected["voice_revision"],
                personality_revision=selected["personality_revision"],
            )
        except PersonSourceAlignmentError as exc:
            raise PersonProfileError(f"person source alignment failed: {exc}") from exc
    profile["active_person_revision"] = revision_id
    saved = _save(root, profile)
    return load_profile(root, person_id) if saved.get("source") is not None else saved
