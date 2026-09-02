from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from pathlib import Path
from typing import Any, Mapping

from .package import MRBodyError, validate_package
from .personality_blueprint import blueprint_sha256, compile_blueprint, validate_blueprint

FORMAT = "bodyrig-personality-embodiment-binding"
VERSION = 1
PERSON_ID_RE = re.compile(r"^person-[0-9a-f]{32}$")
PERSONALITY_REVISION_RE = re.compile(r"^personality-r[0-9]{4}$")
BODY_REVISION_RE = re.compile(r"^body-r[0-9]{4}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
STYLE_EVIDENCE_SUFFIX_RE = re.compile(
    r"^ \| style_report_sha256=[0-9a-f]{64} \| style_approval_sha256=[0-9a-f]{64}$"
)

BLUEPRINT_BODYPRINT_FIELDS = {
    "movement_energy": ("motion", "energy"),
    "gesture_frequency": ("motion", "gesture_frequency"),
    "gesture_amplitude": ("motion", "gesture_amplitude"),
    "head_motion": ("motion", "head_motion"),
    "gaze_strength": ("expression", "gaze_strength"),
    "speech_motion": ("expression", "speech_motion"),
}


class PersonalityEmbodimentBindingError(ValueError):
    pass


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
    except OSError as exc:
        raise PersonalityEmbodimentBindingError("registered body package could not be hashed") from exc
    return digest.hexdigest()


def _find_revision(profile: Mapping[str, Any], kind: str, revision_id: str) -> dict[str, Any]:
    collection = profile.get(f"{kind}_revisions")
    if not isinstance(collection, list):
        raise PersonalityEmbodimentBindingError(f"{kind} revisions are missing")
    for item in collection:
        if isinstance(item, Mapping) and item.get("revision_id") == revision_id:
            return dict(item)
    raise PersonalityEmbodimentBindingError(f"unknown {kind} revision")


def _verify_personality_compilation(
    blueprint: Mapping[str, Any],
    personality: Mapping[str, Any],
) -> None:
    compiled = compile_blueprint(blueprint)
    if str(personality.get("instructions") or "") != compiled["instructions"]:
        raise PersonalityEmbodimentBindingError(
            "personality instructions are not the exact compilation of the bound blueprint"
        )
    if str(personality.get("default_language") or "") != compiled["default_language"]:
        raise PersonalityEmbodimentBindingError(
            "personality language is not the exact compilation of the bound blueprint"
        )

    compiled_style = compiled["style_notes"]
    saved_style = str(personality.get("style_notes") or "")
    if saved_style == compiled_style:
        return
    if not saved_style.startswith(compiled_style):
        raise PersonalityEmbodimentBindingError(
            "personality style notes are not the exact compilation of the bound blueprint"
        )
    suffix = saved_style[len(compiled_style):]
    if STYLE_EVIDENCE_SUFFIX_RE.fullmatch(suffix) is None:
        raise PersonalityEmbodimentBindingError(
            "personality style notes contain an unsupported suffix after blueprint compilation"
        )


def _bodyprint_for_revision(profile: Mapping[str, Any], revision_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    body = _find_revision(profile, "body", revision_id)
    package = Path(str(body.get("package_path") or "")).expanduser().resolve()
    if not package.is_file():
        raise PersonalityEmbodimentBindingError("registered body package is missing")
    if _sha256_file(package) != body.get("package_sha256"):
        raise PersonalityEmbodimentBindingError("registered body package bytes no longer match the body revision")
    try:
        validated = validate_package(package)
    except (MRBodyError, OSError) as exc:
        raise PersonalityEmbodimentBindingError(f"registered body package is invalid: {exc}") from exc
    if validated.manifest.get("id") != body.get("body_id"):
        raise PersonalityEmbodimentBindingError("registered body identity no longer matches its package")
    return body, dict(validated.bodyprint)


def _is_observed_number(bodyprint: Mapping[str, Any], section: str, field: str) -> bool:
    value_section = bodyprint.get(section)
    if not isinstance(value_section, Mapping) or field not in value_section:
        return False
    value = value_section[field]
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def _field_evidence(bodyprint: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    observed: list[str] = []
    fallback: list[str] = []
    for blueprint_field, (section, bodyprint_field) in sorted(BLUEPRINT_BODYPRINT_FIELDS.items()):
        if _is_observed_number(bodyprint, section, bodyprint_field):
            observed.append(blueprint_field)
        else:
            fallback.append(blueprint_field)
    return observed, fallback


def binding_path(
    root: str | os.PathLike[str],
    person_id: str,
    personality_revision: str,
) -> Path:
    if not PERSON_ID_RE.fullmatch(person_id):
        raise PersonalityEmbodimentBindingError("person_id is invalid")
    if not PERSONALITY_REVISION_RE.fullmatch(personality_revision):
        raise PersonalityEmbodimentBindingError("personality revision id is invalid")
    return (
        Path(root).expanduser().resolve()
        / "personality-embodiment-bindings"
        / person_id
        / f"{personality_revision}.json"
    )


def blueprint_evidence_path(
    root: str | os.PathLike[str],
    person_id: str,
    digest: str,
) -> Path:
    if not PERSON_ID_RE.fullmatch(person_id):
        raise PersonalityEmbodimentBindingError("person_id is invalid")
    if not SHA256_RE.fullmatch(digest):
        raise PersonalityEmbodimentBindingError("blueprint SHA-256 is invalid")
    return (
        Path(root).expanduser().resolve()
        / "personality-blueprints"
        / person_id
        / f"{digest}.json"
    )


def read_blueprint_evidence(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    digest: str,
) -> dict[str, Any]:
    path = blueprint_evidence_path(root, person_id, digest)
    if not path.is_file():
        raise PersonalityEmbodimentBindingError("bound personality blueprint evidence is missing")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        normalized = validate_blueprint(value)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise PersonalityEmbodimentBindingError("bound personality blueprint evidence is invalid") from exc
    if blueprint_sha256(normalized) != digest:
        raise PersonalityEmbodimentBindingError("bound personality blueprint evidence SHA-256 mismatch")
    return normalized


def build_binding(
    profile: Mapping[str, Any],
    *,
    personality_revision: str,
    blueprint: Mapping[str, Any],
) -> dict[str, Any]:
    person_id = profile.get("person_id")
    if not isinstance(person_id, str) or not PERSON_ID_RE.fullmatch(person_id):
        raise PersonalityEmbodimentBindingError("person_id is invalid")
    if not PERSONALITY_REVISION_RE.fullmatch(personality_revision):
        raise PersonalityEmbodimentBindingError("personality revision id is invalid")

    normalized_blueprint = validate_blueprint(blueprint)
    grounding = normalized_blueprint["grounding"]
    if grounding["communication"] != "operator-authored":
        raise PersonalityEmbodimentBindingError("inner/conversational personality must remain operator-authored")

    personality = _find_revision(profile, "personality", personality_revision)
    _verify_personality_compilation(normalized_blueprint, personality)
    personality_receipt = {
        "revision_id": personality_revision,
        "instructions_sha256": _sha256_text(str(personality["instructions"])),
        "style_notes_sha256": _sha256_text(str(personality.get("style_notes") or "")),
    }

    body_receipt: dict[str, Any] | None = None
    observed_fields: list[str] = []
    fallback_fields: list[str] = []
    body_revision = grounding["body_revision"]
    if body_revision is not None:
        if not BODY_REVISION_RE.fullmatch(body_revision):
            raise PersonalityEmbodimentBindingError("blueprint body revision is invalid")
        body, bodyprint = _bodyprint_for_revision(profile, body_revision)
        observed_fields, fallback_fields = _field_evidence(bodyprint)
        body_receipt = {
            "revision_id": body_revision,
            "body_id": body["body_id"],
            "package_sha256": body["package_sha256"],
        }
    elif grounding["embodiment"] != "operator-authored":
        raise PersonalityEmbodimentBindingError("body-derived embodiment is missing its body revision")

    if body_receipt is None:
        evidence_status = "operator-authored"
    elif fallback_fields:
        evidence_status = "partial-observed"
    else:
        evidence_status = "complete-observed"

    return {
        "format": FORMAT,
        "version": VERSION,
        "person_id": person_id,
        "personality": personality_receipt,
        "blueprint_sha256": blueprint_sha256(normalized_blueprint),
        "grounding": {
            "communication": "operator-authored",
            "embodiment": grounding["embodiment"],
            "body_revision": body_revision,
        },
        "body": body_receipt,
        "embodiment_evidence": {
            "status": evidence_status,
            "observed_fields": observed_fields,
            "neutral_fallback_fields": fallback_fields,
        },
        "human_review_required": True,
        "production_authority": False,
    }


def _encode(value: Mapping[str, Any]) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        allow_nan=False,
    ) + "\n"


def write_binding(
    root: str | os.PathLike[str],
    profile: Mapping[str, Any],
    *,
    personality_revision: str,
    blueprint: Mapping[str, Any],
) -> Path:
    payload = build_binding(
        profile,
        personality_revision=personality_revision,
        blueprint=blueprint,
    )
    target = binding_path(root, str(payload["person_id"]), personality_revision)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = _encode(payload)
    temp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temp, target)
        except FileExistsError:
            try:
                existing = target.read_text(encoding="utf-8")
            except OSError as exc:
                raise PersonalityEmbodimentBindingError("existing embodiment binding is unreadable") from exc
            if existing != encoded:
                raise PersonalityEmbodimentBindingError("embodiment binding already exists with different bytes")
        except OSError as exc:
            raise PersonalityEmbodimentBindingError("could not commit embodiment binding create-only") from exc
    finally:
        temp.unlink(missing_ok=True)
    return target


def read_binding(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    personality_revision: str,
) -> dict[str, Any]:
    path = binding_path(root, person_id, personality_revision)
    if not path.is_file():
        raise PersonalityEmbodimentBindingError("personality revision has no embodiment binding")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonalityEmbodimentBindingError("embodiment binding is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PersonalityEmbodimentBindingError("embodiment binding must be an object")
    return value


def verify_binding(
    profile: Mapping[str, Any],
    binding: Mapping[str, Any],
    *,
    selected_body_revision: str | None = None,
    blueprint: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if not isinstance(binding, Mapping):
        raise PersonalityEmbodimentBindingError("embodiment binding must be an object")
    required = {
        "format",
        "version",
        "person_id",
        "personality",
        "blueprint_sha256",
        "grounding",
        "body",
        "embodiment_evidence",
        "human_review_required",
        "production_authority",
    }
    if set(binding) != required or binding.get("format") != FORMAT or binding.get("version") != VERSION:
        raise PersonalityEmbodimentBindingError("embodiment binding fields/version are invalid")
    if binding.get("person_id") != profile.get("person_id"):
        raise PersonalityEmbodimentBindingError("embodiment binding person identity mismatch")
    if binding.get("human_review_required") is not True or binding.get("production_authority") is not False:
        raise PersonalityEmbodimentBindingError("embodiment binding authority boundary is invalid")

    personality = binding.get("personality")
    if not isinstance(personality, Mapping) or set(personality) != {
        "revision_id",
        "instructions_sha256",
        "style_notes_sha256",
    }:
        raise PersonalityEmbodimentBindingError("embodiment binding personality receipt is invalid")
    revision_id = personality.get("revision_id")
    if not isinstance(revision_id, str) or not PERSONALITY_REVISION_RE.fullmatch(revision_id):
        raise PersonalityEmbodimentBindingError("embodiment binding personality revision is invalid")
    saved = _find_revision(profile, "personality", revision_id)
    if personality.get("instructions_sha256") != _sha256_text(str(saved["instructions"])):
        raise PersonalityEmbodimentBindingError("personality instructions no longer match embodiment binding")
    if personality.get("style_notes_sha256") != _sha256_text(str(saved.get("style_notes") or "")):
        raise PersonalityEmbodimentBindingError("personality style notes no longer match embodiment binding")

    digest = binding.get("blueprint_sha256")
    if not isinstance(digest, str) or not SHA256_RE.fullmatch(digest):
        raise PersonalityEmbodimentBindingError("embodiment binding blueprint SHA-256 is invalid")
    if blueprint is not None:
        normalized_blueprint = validate_blueprint(blueprint)
        if blueprint_sha256(normalized_blueprint) != digest:
            raise PersonalityEmbodimentBindingError("blueprint bytes/semantics no longer match embodiment binding")
        if dict(binding.get("grounding") or {}) != normalized_blueprint["grounding"]:
            raise PersonalityEmbodimentBindingError("blueprint grounding no longer matches embodiment binding")
        _verify_personality_compilation(normalized_blueprint, saved)

    grounding = binding.get("grounding")
    if not isinstance(grounding, Mapping) or set(grounding) != {
        "communication",
        "embodiment",
        "body_revision",
    }:
        raise PersonalityEmbodimentBindingError("embodiment binding grounding is invalid")
    if grounding.get("communication") != "operator-authored":
        raise PersonalityEmbodimentBindingError("embodiment binding may not infer inner personality from body/video")

    body = binding.get("body")
    evidence = binding.get("embodiment_evidence")
    if not isinstance(evidence, Mapping) or set(evidence) != {
        "status",
        "observed_fields",
        "neutral_fallback_fields",
    }:
        raise PersonalityEmbodimentBindingError("embodiment evidence receipt is invalid")

    body_revision = grounding.get("body_revision")
    if body_revision is None:
        if body is not None or evidence.get("status") != "operator-authored":
            raise PersonalityEmbodimentBindingError("operator-authored embodiment has unexpected body evidence")
        if evidence.get("observed_fields") != [] or evidence.get("neutral_fallback_fields") != []:
            raise PersonalityEmbodimentBindingError("operator-authored embodiment claims observed body fields")
    else:
        if selected_body_revision is not None and selected_body_revision != body_revision:
            raise PersonalityEmbodimentBindingError("selected body revision conflicts with personality embodiment binding")
        if not isinstance(body, Mapping) or set(body) != {"revision_id", "body_id", "package_sha256"}:
            raise PersonalityEmbodimentBindingError("body-derived embodiment body receipt is invalid")
        current_body, bodyprint = _bodyprint_for_revision(profile, str(body_revision))
        expected_body = {
            "revision_id": body_revision,
            "body_id": current_body["body_id"],
            "package_sha256": current_body["package_sha256"],
        }
        if dict(body) != expected_body:
            raise PersonalityEmbodimentBindingError("body revision/package no longer matches embodiment binding")
        observed_fields, fallback_fields = _field_evidence(bodyprint)
        expected_status = "partial-observed" if fallback_fields else "complete-observed"
        if evidence.get("status") != expected_status:
            raise PersonalityEmbodimentBindingError("embodiment evidence status no longer matches BodyPrint")
        if evidence.get("observed_fields") != observed_fields or evidence.get("neutral_fallback_fields") != fallback_fields:
            raise PersonalityEmbodimentBindingError("embodiment field evidence no longer matches BodyPrint")

    return dict(binding)
