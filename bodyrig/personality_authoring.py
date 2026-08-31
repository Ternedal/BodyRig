from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from .package import MRBodyError, validate_package
from .person_profiles import PersonProfileError, add_personality_revision, load_profile
from .personality_audition_suite import build_audition_suite
from .personality_blueprint import (
    PersonalityBlueprintError,
    blueprint_sha256,
    build_blueprint,
    compile_blueprint,
    validate_blueprint,
)


class PersonalityAuthoringError(ValueError):
    pass


def _find_body_revision(profile: Mapping[str, Any], revision_id: str) -> dict[str, Any]:
    for item in profile.get("body_revisions", []):
        if item.get("revision_id") == revision_id:
            return dict(item)
    raise PersonalityAuthoringError(f"body revision {revision_id!r} is not registered on this person")


def _validated_bodyprint(profile: Mapping[str, Any], revision_id: str) -> dict[str, Any]:
    item = _find_body_revision(profile, revision_id)
    package = Path(str(item["package_path"])).expanduser().resolve()
    if not package.is_file():
        raise PersonalityAuthoringError("registered body package is missing")
    try:
        validated = validate_package(package)
    except (MRBodyError, OSError) as exc:
        raise PersonalityAuthoringError(f"registered body package is invalid: {exc}") from exc
    if validated.manifest["id"] != item["body_id"]:
        raise PersonalityAuthoringError("registered body identity no longer matches its .mrbody package")
    import hashlib

    digest = hashlib.sha256(package.read_bytes()).hexdigest()
    if digest != item["package_sha256"]:
        raise PersonalityAuthoringError("registered body package bytes no longer match the body revision")
    return dict(validated.bodyprint)


def build_guided_personality(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    default_language: str,
    communication: Mapping[str, Any],
    authored_notes: str = "",
    style_exemplars: Sequence[str] | None = None,
    body_revision: str | None = None,
) -> dict[str, Any]:
    try:
        profile = load_profile(root, person_id)
    except PersonProfileError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc

    bodyprint = None
    if body_revision:
        bodyprint = _validated_bodyprint(profile, body_revision)
    try:
        blueprint = build_blueprint(
            default_language=default_language,
            communication=communication,
            authored_notes=authored_notes,
            style_exemplars=style_exemplars,
            bodyprint=bodyprint,
            body_revision=body_revision,
        )
        candidate = compile_blueprint(blueprint)
    except PersonalityBlueprintError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc
    return {
        "blueprint": blueprint,
        "blueprint_sha256": blueprint_sha256(blueprint),
        "candidate": candidate,
        "audition_suite": build_audition_suite(candidate["default_language"]),
    }


def _evidence_path(root: Path, person_id: str, digest: str) -> Path:
    return root / "personality-blueprints" / person_id / f"{digest}.json"


def persist_blueprint_evidence(
    root: str | os.PathLike[str],
    person_id: str,
    blueprint: Mapping[str, Any],
) -> Path:
    root_path = Path(root).expanduser().resolve()
    try:
        load_profile(root_path, person_id)
        normalized = validate_blueprint(blueprint)
    except (PersonProfileError, PersonalityBlueprintError) as exc:
        raise PersonalityAuthoringError(str(exc)) from exc
    digest = blueprint_sha256(normalized)
    path = _evidence_path(root_path, person_id, digest)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        normalized,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"
    if path.exists():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise PersonalityAuthoringError("existing personality blueprint evidence is unreadable") from exc
        if existing != encoded:
            raise PersonalityAuthoringError("personality blueprint digest path contains different bytes")
        return path

    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, path)
        except FileExistsError:
            existing = path.read_text(encoding="utf-8")
            if existing != encoded:
                raise PersonalityAuthoringError("personality blueprint evidence raced with different bytes")
        except OSError as exc:
            raise PersonalityAuthoringError("could not commit personality blueprint evidence create-only") from exc
    finally:
        temp.unlink(missing_ok=True)
    return path


def save_guided_personality(
    root: str | os.PathLike[str],
    person_id: str,
    *,
    default_language: str,
    communication: Mapping[str, Any],
    authored_notes: str = "",
    style_exemplars: Sequence[str] | None = None,
    body_revision: str | None = None,
    feedback: str = "",
) -> dict[str, Any]:
    result = build_guided_personality(
        root,
        person_id,
        default_language=default_language,
        communication=communication,
        authored_notes=authored_notes,
        style_exemplars=style_exemplars,
        body_revision=body_revision,
    )
    evidence = persist_blueprint_evidence(root, person_id, result["blueprint"])
    candidate = result["candidate"]
    try:
        profile = add_personality_revision(
            root,
            person_id,
            instructions=candidate["instructions"],
            default_language=candidate["default_language"],
            style_notes=candidate["style_notes"],
            feedback=feedback,
        )
    except PersonProfileError as exc:
        raise PersonalityAuthoringError(str(exc)) from exc
    return {
        **result,
        "evidence_path": str(evidence),
        "profile": profile,
        "saved_personality_revision": profile["personality_revisions"][-1]["revision_id"],
    }
