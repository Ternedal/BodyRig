from __future__ import annotations

import os
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .stash_source import StashClient, StashSourceError


_AUTHORITY = {
    "context_only": True,
    "personality_trait_authority": False,
    "personality_inference_authority": False,
    "biography_authority": False,
    "activation_authority": False,
    "production_authority": False,
}


def _safe_number(value: Any) -> float:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if parsed >= 0 else 0.0


def _scene_performer_ids(scene: Mapping[str, Any]) -> set[str]:
    return {
        str(item.get("id"))
        for item in (scene.get("performers") or [])
        if isinstance(item, Mapping) and item.get("id") is not None
    }


def _scene_tags(scene: Mapping[str, Any]) -> list[str]:
    values = {
        str(item.get("name") or "").strip()
        for item in (scene.get("tags") or [])
        if isinstance(item, Mapping)
    }
    return sorted(value for value in values if value)


def _scene_summary(scene: Mapping[str, Any]) -> dict[str, Any]:
    files = [
        item
        for item in (scene.get("files") or [])
        if isinstance(item, Mapping)
    ]
    max_width = 0
    max_height = 0
    total_duration = 0.0
    codecs: set[str] = set()
    local_files = 0
    for item in files:
        width = int(_safe_number(item.get("width")))
        height = int(_safe_number(item.get("height")))
        max_width = max(max_width, width)
        max_height = max(max_height, height)
        total_duration = max(total_duration, _safe_number(item.get("duration")))
        codec = str(item.get("video_codec") or "").strip()
        if codec:
            codecs.add(codec)
        raw_path = str(item.get("path") or "").strip()
        if raw_path:
            try:
                if Path(raw_path).expanduser().is_file():
                    local_files += 1
            except OSError:
                pass
    performer_ids = _scene_performer_ids(scene)
    return {
        "scene_id": str(scene.get("id") or ""),
        "title": str(scene.get("title") or "").strip(),
        "performer_count": len(performer_ids),
        "tags": _scene_tags(scene)[:12],
        "file_count": len(files),
        "local_file_count": local_files,
        "max_width": max_width,
        "max_height": max_height,
        "duration_seconds": total_duration,
        "video_codecs": sorted(codecs),
    }


def inspect_personality_stash_context(
    profile: Mapping[str, Any],
    *,
    stash_client: StashClient | None = None,
    scene_limit: int = 200,
) -> dict[str, Any]:
    person_id = str(profile.get("person_id") or "")
    display_name = str(profile.get("display_name") or "")
    source = profile.get("source")

    base = {
        "person_id": person_id,
        "display_name": display_name,
        "authority": dict(_AUTHORITY),
    }
    if not isinstance(source, Mapping) or source.get("kind") != "stash-performer":
        return {
            **base,
            "available": False,
            "reason": "Personen er ikke bundet til en Stash performer.",
            "performer": None,
        }

    performer_id = str(source.get("performer_id") or "").strip()
    if not performer_id:
        return {
            **base,
            "available": False,
            "reason": "Personens Stash-binding mangler performer-id.",
            "performer": None,
        }
    bound_performer = {
        "id": performer_id,
        "name": str(source.get("performer_name") or ""),
        "disambiguation": str(source.get("disambiguation") or ""),
    }

    if stash_client is None:
        return {
            **base,
            "available": False,
            "reason": "Stash er ikke konfigureret for BodyRig-servicen.",
            "performer": bound_performer,
        }

    try:
        version = stash_client.version()
        performer = stash_client.performer(performer_id)
        scenes = stash_client.scenes_for_performer(
            performer_id,
            limit=scene_limit,
        )
    except StashSourceError as exc:
        return {
            **base,
            "available": False,
            "reason": str(exc),
            "performer": bound_performer,
        }

    if str(performer.get("id") or "") != performer_id:
        return {
            **base,
            "available": False,
            "reason": "Live Stash performer-id matcher ikke Person-bindingen.",
            "performer": bound_performer,
        }

    solo = 0
    multi = 0
    files = 0
    local_files = 0
    four_k_files = 0
    total_duration = 0.0
    tag_counts: Counter[str] = Counter()
    codec_counts: Counter[str] = Counter()
    resolution_counts: Counter[str] = Counter()
    recent: list[dict[str, Any]] = []

    for scene in scenes:
        if not isinstance(scene, Mapping):
            continue
        performer_ids = _scene_performer_ids(scene)
        if performer_id not in performer_ids:
            # Never trust the server-side performer filter as sole identity proof.
            continue
        if len(performer_ids) == 1:
            solo += 1
        elif len(performer_ids) > 1:
            multi += 1

        tags = _scene_tags(scene)
        tag_counts.update(tags)

        summary = _scene_summary(scene)
        if len(recent) < 12:
            recent.append(summary)

        for item in (scene.get("files") or []):
            if not isinstance(item, Mapping):
                continue
            files += 1
            raw_path = str(item.get("path") or "").strip()
            if raw_path:
                try:
                    if Path(raw_path).expanduser().is_file():
                        local_files += 1
                except OSError:
                    pass
            width = int(_safe_number(item.get("width")))
            height = int(_safe_number(item.get("height")))
            if height >= 2160:
                four_k_files += 1
                resolution_counts["4k_or_higher"] += 1
            elif height >= 1440:
                resolution_counts["1440p"] += 1
            elif height >= 1080:
                resolution_counts["1080p"] += 1
            elif height > 0:
                resolution_counts["below_1080p"] += 1
            else:
                resolution_counts["unknown"] += 1
            total_duration += _safe_number(item.get("duration"))
            codec = str(item.get("video_codec") or "").strip()
            if codec:
                codec_counts[codec] += 1

    top_tags = [
        {"name": name, "count": count}
        for name, count in sorted(
            tag_counts.items(),
            key=lambda item: (-item[1], item[0].casefold()),
        )[:20]
    ]
    codecs = [
        {"name": name, "count": count}
        for name, count in sorted(
            codec_counts.items(),
            key=lambda item: (-item[1], item[0].casefold()),
        )
    ]

    return {
        **base,
        "available": True,
        "reason": None,
        "stash_version": str(version or "unknown"),
        "performer": {
            "id": str(performer.get("id") or performer_id),
            "name": str(performer.get("name") or bound_performer["name"]),
            "disambiguation": str(
                performer.get("disambiguation")
                or bound_performer["disambiguation"]
            ),
        },
        "scene_count_observed": solo + multi,
        "scene_query_limit": scene_limit,
        "scene_count_may_be_truncated": len(scenes) >= scene_limit,
        "solo_scene_count": solo,
        "multi_performer_scene_count": multi,
        "file_count_observed": files,
        "local_file_count_observed": local_files,
        "four_k_file_count_observed": four_k_files,
        "total_file_duration_seconds_observed": total_duration,
        "resolution_counts": dict(sorted(resolution_counts.items())),
        "video_codecs": codecs,
        "top_tags": top_tags,
        "recent_scenes": recent,
        "guidance": (
            "Stash-data er read-only authoring-kontekst. Titler, tags, scene- og "
            "filmetadata må ikke bruges som automatisk evidence for de 120 "
            "personality-traits, private tanker, biografi eller minder."
        ),
    }
