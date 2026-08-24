from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-person-assembly"
VERSION = 1
RECEIPT_FORMAT = "bodyrig-person-assembly-receipt"
RECEIPT_VERSION = 1
PERSON_ID_RE = re.compile(r"^person-[0-9a-f]{32}$")
PERSON_REVISION_RE = re.compile(r"^person-r[0-9]{4}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _fingerprint(canonical: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_assembly(
    profile: Mapping[str, Any],
    *,
    body_revision: str,
    voice_revision: str,
    personality_revision: str,
) -> dict[str, Any]:
    person_id = profile.get("person_id")
    if not isinstance(person_id, str) or not PERSON_ID_RE.fullmatch(person_id):
        raise PersonAssemblyError("person_id is invalid")

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
    return {
        **canonical,
        "assembly_fingerprint": _fingerprint(canonical),
        "personality_preview": {
            "instructions": personality["instructions"],
            "default_language": personality["default_language"],
            "style_notes": personality.get("style_notes") or "",
        },
    }


def receipt_path(root: str | os.PathLike[str], person_id: str, person_revision: str) -> Path:
    if not PERSON_ID_RE.fullmatch(person_id):
        raise PersonAssemblyError("person_id is invalid")
    if not PERSON_REVISION_RE.fullmatch(person_revision):
        raise PersonAssemblyError("person revision id is invalid")
    return Path(root).expanduser().resolve() / "assembly-receipts" / person_id / f"{person_revision}.json"


def _receipt_payload(person_revision: str, assembly: Mapping[str, Any]) -> dict[str, Any]:
    fingerprint = assembly.get("assembly_fingerprint")
    if not isinstance(fingerprint, str) or not SHA256_RE.fullmatch(fingerprint):
        raise PersonAssemblyError("assembly fingerprint is invalid")
    return {
        "format": RECEIPT_FORMAT,
        "version": RECEIPT_VERSION,
        "person_id": assembly["person_id"],
        "person_revision": person_revision,
        "assembly_fingerprint": fingerprint,
        "body": dict(assembly["body"]),
        "voice": dict(assembly["voice"]),
        "personality": {
            "revision_id": assembly["personality"]["revision_id"],
            "instructions_sha256": assembly["personality"]["instructions_sha256"],
            "default_language": assembly["personality"]["default_language"],
            "style_notes_sha256": assembly["personality"]["style_notes_sha256"],
        },
    }


def write_receipt(
    root: str | os.PathLike[str],
    *,
    person_revision: str,
    assembly: Mapping[str, Any],
) -> Path:
    person_id = str(assembly.get("person_id") or "")
    target = receipt_path(root, person_id, person_revision)
    payload = _receipt_payload(person_revision, assembly)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    temp = target.with_name(f"{target.name}.tmp-{uuid.uuid4().hex}")
    try:
        temp.write_text(encoded, encoding="utf-8", newline="\n")
        with target.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
    except FileExistsError as exc:
        raise PersonAssemblyError(f"assembly receipt already exists: {target.name}") from exc
    finally:
        temp.unlink(missing_ok=True)
    return target


def read_receipt(
    root: str | os.PathLike[str],
    *,
    person_id: str,
    person_revision: str,
) -> dict[str, Any]:
    path = receipt_path(root, person_id, person_revision)
    if not path.is_file():
        raise PersonAssemblyError("approved person revision has no assembly receipt")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonAssemblyError("assembly receipt is invalid JSON") from exc
    if not isinstance(value, dict):
        raise PersonAssemblyError("assembly receipt is invalid")
    expected = {
        "format",
        "version",
        "person_id",
        "person_revision",
        "assembly_fingerprint",
        "body",
        "voice",
        "personality",
    }
    if set(value) != expected or value.get("format") != RECEIPT_FORMAT or value.get("version") != RECEIPT_VERSION:
        raise PersonAssemblyError("assembly receipt fields/version are invalid")
    if value.get("person_id") != person_id or value.get("person_revision") != person_revision:
        raise PersonAssemblyError("assembly receipt identity mismatch")
    fingerprint = value.get("assembly_fingerprint")
    if not isinstance(fingerprint, str) or not SHA256_RE.fullmatch(fingerprint):
        raise PersonAssemblyError("assembly receipt fingerprint is invalid")
    return value


def verify_receipt(
    root: str | os.PathLike[str],
    *,
    person_revision: str,
    assembly: Mapping[str, Any],
) -> dict[str, Any]:
    person_id = str(assembly.get("person_id") or "")
    receipt = read_receipt(root, person_id=person_id, person_revision=person_revision)
    expected = _receipt_payload(person_revision, assembly)
    if receipt != expected:
        raise PersonAssemblyError("assembly receipt no longer matches the selected component bytes/text")
    return receipt
