from __future__ import annotations

import hashlib
import json
import os
from typing import Any, Mapping

from .person_assembly import PersonAssemblyError, build_assembly
from .personality_embodiment_binding import (
    PersonalityEmbodimentBindingError,
    read_binding,
    verify_binding,
)

FORMAT = "bodyrig-person-assembly"
VERSION = 2


class EmbodimentAssemblyError(ValueError):
    pass


def _canonical_sha256(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_embodiment_bound_assembly(
    profile: Mapping[str, Any],
    *,
    body_revision: str,
    voice_revision: str,
    personality_revision: str,
    embodiment_binding: Mapping[str, Any],
) -> dict[str, Any]:
    """Build person assembly v2 with an exact personality/body embodiment gate."""

    try:
        verified = verify_binding(
            profile,
            embodiment_binding,
            selected_body_revision=body_revision,
        )
    except PersonalityEmbodimentBindingError as exc:
        raise EmbodimentAssemblyError(str(exc)) from exc

    personality_receipt = verified.get("personality")
    if not isinstance(personality_receipt, Mapping) or personality_receipt.get("revision_id") != personality_revision:
        raise EmbodimentAssemblyError("selected personality revision conflicts with embodiment binding")

    try:
        legacy = build_assembly(
            profile,
            body_revision=body_revision,
            voice_revision=voice_revision,
            personality_revision=personality_revision,
        )
    except PersonAssemblyError as exc:
        raise EmbodimentAssemblyError(str(exc)) from exc

    binding_sha = _canonical_sha256(verified)
    canonical = {
        "format": FORMAT,
        "version": VERSION,
        "person_id": legacy["person_id"],
        "body": dict(legacy["body"]),
        "voice": dict(legacy["voice"]),
        "personality": dict(legacy["personality"]),
        "embodiment_binding": {
            "binding_sha256": binding_sha,
            "blueprint_sha256": verified["blueprint_sha256"],
            "grounding": dict(verified["grounding"]),
            "evidence_status": verified["embodiment_evidence"]["status"],
            "observed_fields": list(verified["embodiment_evidence"]["observed_fields"]),
            "neutral_fallback_fields": list(verified["embodiment_evidence"]["neutral_fallback_fields"]),
        },
    }
    return {
        **canonical,
        "assembly_fingerprint": _canonical_sha256(canonical),
        "personality_preview": dict(legacy["personality_preview"]),
        "human_review_required": True,
        "production_authority": False,
    }


def build_embodiment_bound_assembly_from_library(
    root: str | os.PathLike[str],
    profile: Mapping[str, Any],
    *,
    body_revision: str,
    voice_revision: str,
    personality_revision: str,
) -> dict[str, Any]:
    """Load the create-only binding and build a fail-closed assembly v2."""

    person_id = str(profile.get("person_id") or "")
    try:
        binding = read_binding(
            root,
            person_id=person_id,
            personality_revision=personality_revision,
        )
    except PersonalityEmbodimentBindingError as exc:
        raise EmbodimentAssemblyError(str(exc)) from exc
    return build_embodiment_bound_assembly(
        profile,
        body_revision=body_revision,
        voice_revision=voice_revision,
        personality_revision=personality_revision,
        embodiment_binding=binding,
    )
