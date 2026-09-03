from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .person_source_alignment import PersonSourceAlignmentError, file_sha256, read_binding


class PersonVoiceSourceError(ValueError):
    pass


def source_files_for_body(
    root: str | Path,
    profile: Mapping[str, Any],
    *,
    body_revision: str,
) -> dict[str, Any]:
    source = profile.get("source")
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        raise PersonVoiceSourceError("person has no authoritative Stash performer source")
    try:
        binding = read_binding(root, profile, kind="body", revision_id=body_revision)
    except PersonSourceAlignmentError as exc:
        raise PersonVoiceSourceError(f"body source binding is not authoritative: {exc}") from exc

    evidence = binding.get("evidence")
    if not isinstance(evidence, Mapping):
        raise PersonVoiceSourceError("body source binding has no evidence object")
    bound_files = evidence.get("source_files")
    if not isinstance(bound_files, list) or not bound_files:
        raise PersonVoiceSourceError("body revision has no exact source-file evidence for a VoiceRig build")

    manifest_ref = str(evidence.get("ref") or "").strip()
    if not manifest_ref:
        raise PersonVoiceSourceError("body source binding has no source manifest reference")
    manifest_path = Path(manifest_ref).expanduser().resolve()
    if not manifest_path.is_file():
        raise PersonVoiceSourceError("body source manifest is no longer readable")
    manifest_sha = file_sha256(manifest_path)
    if manifest_sha != str(evidence.get("sha256") or ""):
        raise PersonVoiceSourceError("body source manifest no longer matches its source binding")

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PersonVoiceSourceError("body source manifest is unreadable") from exc
    if not isinstance(manifest, Mapping) or manifest.get("format") != "bodyrig-stash-source-manifest" or manifest.get("version") != 1:
        raise PersonVoiceSourceError("body source manifest format/version mismatch")
    performer = manifest.get("performer")
    if not isinstance(performer, Mapping):
        raise PersonVoiceSourceError("body source manifest performer is missing")
    if str(performer.get("id") or "") != str(source.get("performer_id") or ""):
        raise PersonVoiceSourceError("body source manifest performer id no longer matches the Person source")
    if str(performer.get("name") or "") != str(source.get("performer_name") or ""):
        raise PersonVoiceSourceError("body source manifest performer name no longer matches the Person source")

    selected = manifest.get("selected")
    if not isinstance(selected, list) or not selected:
        raise PersonVoiceSourceError("body source manifest has no selected media")
    if len(selected) != len(bound_files):
        raise PersonVoiceSourceError("body source manifest file count no longer matches its source binding")

    files: list[dict[str, str]] = []
    for index, (item, bound) in enumerate(zip(selected, bound_files, strict=True), start=1):
        if not isinstance(item, Mapping) or not isinstance(bound, Mapping):
            raise PersonVoiceSourceError(f"body source entry {index} is invalid")
        path = Path(str(item.get("path") or "")).expanduser().resolve()
        if not path.is_file():
            raise PersonVoiceSourceError(f"body source file {index} is no longer readable: {path.name or '?'}")
        scene_id = str(item.get("scene_id") or "")
        if scene_id != str(bound.get("scene_id") or "") or path.name != str(bound.get("name") or ""):
            raise PersonVoiceSourceError(f"body source file {index} identity no longer matches its source binding")
        sha = file_sha256(path)
        if sha != str(bound.get("sha256") or ""):
            raise PersonVoiceSourceError(f"body source file {index} bytes no longer match its source binding")
        files.append({
            "scene_id": scene_id,
            "name": path.name,
            "sha256": sha,
            "path": str(path),
        })

    return {
        "body_revision": body_revision,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha,
        "source_files": files,
    }
