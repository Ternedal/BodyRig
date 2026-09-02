from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

FORMAT = "bodyrig-person-source-binding"
VERSION = 1
_KINDS = {"body", "voice", "personality"}
_REVISION_RE = re.compile(r"^(body|voice|personality)-r[0-9]{4}$")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


class PersonSourceAlignmentError(ValueError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def canonical_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return _sha_bytes(raw)


def file_sha256(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source(profile: Mapping[str, Any]) -> dict[str, str]:
    source = profile.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        raise PersonSourceAlignmentError("person has no authoritative Stash performer source")
    performer_id = str(source.get("performer_id") or "").strip()
    performer_name = str(source.get("performer_name") or "").strip()
    if not performer_id or not performer_name:
        raise PersonSourceAlignmentError("person source is incomplete")
    return {
        "kind": "stash-performer",
        "performer_id": performer_id,
        "performer_name": performer_name,
        "disambiguation": str(source.get("disambiguation") or ""),
    }


def _component(profile: Mapping[str, Any], kind: str, revision_id: str) -> Mapping[str, Any]:
    if kind not in _KINDS:
        raise PersonSourceAlignmentError("unsupported component kind")
    if not _REVISION_RE.fullmatch(revision_id) or not revision_id.startswith(f"{kind}-r"):
        raise PersonSourceAlignmentError("invalid component revision")
    for item in profile.get(f"{kind}_revisions", []):
        if isinstance(item, Mapping) and item.get("revision_id") == revision_id:
            return item
    raise PersonSourceAlignmentError(f"unknown {kind} revision")


def component_artifact_sha256(profile: Mapping[str, Any], kind: str, revision_id: str) -> str:
    item = _component(profile, kind, revision_id)
    if kind in {"body", "voice"}:
        value = str(item.get("package_sha256") or "").strip().lower()
        if not _SHA_RE.fullmatch(value):
            raise PersonSourceAlignmentError(f"{kind} revision has invalid package SHA-256")
        return value
    payload = {
        "revision_id": item.get("revision_id"),
        "instructions": item.get("instructions"),
        "default_language": item.get("default_language"),
        "style_notes": item.get("style_notes"),
    }
    return canonical_sha256(payload)


def _binding_dir(root: str | os.PathLike[str], person_id: str) -> Path:
    return Path(root).expanduser().resolve() / ".source-bindings" / person_id


def binding_path(root: str | os.PathLike[str], person_id: str, kind: str, revision_id: str) -> Path:
    if kind not in _KINDS or not _REVISION_RE.fullmatch(revision_id) or not revision_id.startswith(f"{kind}-r"):
        raise PersonSourceAlignmentError("invalid source binding key")
    return _binding_dir(root, person_id) / f"{revision_id}.json"


def _same_binding(existing: Mapping[str, Any], candidate: Mapping[str, Any]) -> bool:
    return (
        existing.get("format") == candidate.get("format")
        and existing.get("version") == candidate.get("version")
        and existing.get("person_id") == candidate.get("person_id")
        and existing.get("source") == candidate.get("source")
        and existing.get("component") == candidate.get("component")
        and existing.get("evidence") == candidate.get("evidence")
    )


def write_binding(
    root: str | os.PathLike[str],
    profile: Mapping[str, Any],
    *,
    kind: str,
    revision_id: str,
    evidence_kind: str,
    evidence_sha256: str,
    evidence_ref: str,
    source_files: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    person_id = str(profile.get("person_id") or "").strip()
    if not person_id:
        raise PersonSourceAlignmentError("person id is required")
    source = _source(profile)
    artifact_sha = component_artifact_sha256(profile, kind, revision_id)
    evidence_sha256 = str(evidence_sha256 or "").strip().lower()
    if not _SHA_RE.fullmatch(evidence_sha256):
        raise PersonSourceAlignmentError("evidence_sha256 must be lowercase SHA-256")
    evidence_kind = str(evidence_kind or "").strip()
    evidence_ref = str(evidence_ref or "").strip()
    if not evidence_kind or not evidence_ref or len(evidence_kind) > 120 or len(evidence_ref) > 4096:
        raise PersonSourceAlignmentError("source evidence kind/ref is invalid")
    clean_files: list[dict[str, Any]] = []
    for item in source_files or []:
        if not isinstance(item, Mapping):
            raise PersonSourceAlignmentError("source_files entries must be objects")
        sha = str(item.get("sha256") or "").strip().lower()
        if not _SHA_RE.fullmatch(sha):
            raise PersonSourceAlignmentError("source file SHA-256 is invalid")
        clean_files.append({
            "scene_id": str(item.get("scene_id") or ""),
            "name": str(item.get("name") or "")[:255],
            "sha256": sha,
        })
    receipt = {
        "format": FORMAT,
        "version": VERSION,
        "person_id": person_id,
        "source": source,
        "component": {
            "kind": kind,
            "revision_id": revision_id,
            "artifact_sha256": artifact_sha,
        },
        "evidence": {
            "kind": evidence_kind,
            "sha256": evidence_sha256,
            "ref": evidence_ref,
            "source_files": clean_files,
        },
        "created_utc": _now(),
    }
    path = binding_path(root, person_id, kind, revision_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        existing = read_binding(root, profile, kind=kind, revision_id=revision_id)
        if not _same_binding(existing, receipt):
            raise PersonSourceAlignmentError(f"source binding already exists for {revision_id} with different evidence")
        return existing
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n")
        try:
            os.link(temp, path)
        except FileExistsError:
            existing = read_binding(root, profile, kind=kind, revision_id=revision_id)
            if not _same_binding(existing, receipt):
                raise PersonSourceAlignmentError(f"source binding raced with different evidence for {revision_id}")
        finally:
            temp.unlink(missing_ok=True)
    finally:
        temp.unlink(missing_ok=True)
    return read_binding(root, profile, kind=kind, revision_id=revision_id)


def read_binding(
    root: str | os.PathLike[str],
    profile: Mapping[str, Any],
    *,
    kind: str,
    revision_id: str,
) -> dict[str, Any]:
    path = binding_path(root, str(profile.get("person_id") or ""), kind, revision_id)
    if not path.is_file():
        raise PersonSourceAlignmentError(f"source binding missing for {revision_id}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonSourceAlignmentError(f"source binding is unreadable for {revision_id}") from exc
    if not isinstance(value, Mapping) or value.get("format") != FORMAT or value.get("version") != VERSION:
        raise PersonSourceAlignmentError(f"source binding format/version invalid for {revision_id}")
    if value.get("person_id") != profile.get("person_id") or value.get("source") != _source(profile):
        raise PersonSourceAlignmentError(f"source binding identity mismatch for {revision_id}")
    component = value.get("component")
    if not isinstance(component, Mapping) or component.get("kind") != kind or component.get("revision_id") != revision_id:
        raise PersonSourceAlignmentError(f"source binding component mismatch for {revision_id}")
    if component.get("artifact_sha256") != component_artifact_sha256(profile, kind, revision_id):
        raise PersonSourceAlignmentError(f"source binding artifact mismatch for {revision_id}")
    evidence = value.get("evidence")
    if not isinstance(evidence, Mapping) or not _SHA_RE.fullmatch(str(evidence.get("sha256") or "")):
        raise PersonSourceAlignmentError(f"source binding evidence invalid for {revision_id}")
    return dict(value)


def alignment_status(
    root: str | os.PathLike[str],
    profile: Mapping[str, Any],
    *,
    body_revision: str | None = None,
    voice_revision: str | None = None,
    personality_revision: str | None = None,
) -> dict[str, Any]:
    requested = {
        "body": body_revision,
        "voice": voice_revision,
        "personality": personality_revision,
    }
    result: dict[str, Any] = {
        "source": None,
        "aligned": False,
        "components": {},
        "blockers": [],
    }
    try:
        result["source"] = _source(profile)
    except PersonSourceAlignmentError as exc:
        result["blockers"].append(str(exc))
        return result
    for kind, revision_id in requested.items():
        if not revision_id:
            result["components"][kind] = {"revision_id": None, "aligned": False, "reason": "no revision selected"}
            result["blockers"].append(f"{kind}: no revision selected")
            continue
        try:
            receipt = read_binding(root, profile, kind=kind, revision_id=revision_id)
            result["components"][kind] = {
                "revision_id": revision_id,
                "aligned": True,
                "evidence_kind": receipt["evidence"]["kind"],
                "evidence_sha256": receipt["evidence"]["sha256"],
            }
        except PersonSourceAlignmentError as exc:
            result["components"][kind] = {"revision_id": revision_id, "aligned": False, "reason": str(exc)}
            result["blockers"].append(f"{kind}: {exc}")
    result["aligned"] = not result["blockers"]
    return result


def require_alignment(
    root: str | os.PathLike[str],
    profile: Mapping[str, Any],
    *,
    body_revision: str,
    voice_revision: str,
    personality_revision: str,
) -> dict[str, Any]:
    status = alignment_status(
        root,
        profile,
        body_revision=body_revision,
        voice_revision=voice_revision,
        personality_revision=personality_revision,
    )
    if not status["aligned"]:
        raise PersonSourceAlignmentError("source alignment failed: " + "; ".join(status["blockers"]))
    return status
