from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

FORMAT = "bodyrig-person-assembly"
VERSION = 1


class PersonAssemblyError(ValueError):
    pass


def _find(profile: Mapping[str, Any], kind: str, revision_id: str) -> dict[str, Any]:
    collection = profile.get(f"{kind}_revisions")
    if not isinstance(collection, list):
        raise PersonAssemblyError(f"{kind} revisions are missing")
    for item in collection:
        if isinstance(item, Mapping) and item.get("revision_id") == revision_id:
            return dict(item)
    raise PersonAssemblyError(f"unknown {kind} revision")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_assembly(
    profile: Mapping[str, Any],
    *,
    body_revision: str,
    voice_revision: str,
    personality_revision: str,
) -> dict[str, Any]:
    person_id = profile.get("person_id")
    if not isinstance(person_id, str) or not person_id:
        raise PersonAssemblyError("person_id is missing")

    body = _find(profile, "body", body_revision)
    voice = _find(profile, "voice", voice_revision)
    personality = _find(profile, "personality", personality_revision)

    canonical = {
        "format": FORMAT,
        "version": VERSION,
        "person_id": person_id,
        "body": {
            "revision_id": body["revision_id"],
            "body_id": body["body_id"],
            "package_sha256": body["package_sha256"],
        },
        "voice": {
            "revision_id": voice["revision_id"],
            "voice_id": voice["voice_id"],
            "voice_package": voice["voice_package"],
            "package_sha256": voice["package_sha256"],
        },
        "personality": {
            "revision_id": personality["revision_id"],
            "instructions_sha256": _sha256_text(personality["instructions"]),
            "default_language": personality["default_language"],
            "style_notes_sha256": _sha256_text(personality.get("style_notes") or ""),
        },
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {
        **canonical,
        "assembly_fingerprint": hashlib.sha256(encoded).hexdigest(),
        "personality_preview": {
            "instructions": personality["instructions"],
            "default_language": personality["default_language"],
            "style_notes": personality.get("style_notes") or "",
        },
    }
