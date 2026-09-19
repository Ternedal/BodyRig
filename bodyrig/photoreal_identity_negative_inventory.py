from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from .photoidentity_stash_inventory import fetch_exhaustive_performer_scenes
from .photoreal_stash_inventory import (
    DEFAULT_PAGE_SIZE,
    PhotorealStashInventoryError,
    fetch_photoreal_source_inventory,
)
from .stash_source import StashClient, StashSourceError

FORMAT = "bodyrig-photoreal-identity-negative-inventory"
VERSION = 1
LABEL_AUTHORITY = "stash-single-performer-other-id-v1"
DEFAULT_MAX_NEGATIVE_PERFORMERS = 4
DEFAULT_SOURCES_PER_PERFORMER = 3
MAX_NEGATIVE_PERFORMERS = 16
MAX_SOURCES_PER_PERFORMER = 12
CALIBRATION_VIDEO_PROJECTIONS = {"flat"}
CALIBRATION_VIDEO_STEREO_LAYOUTS = {"mono", "side-by-side", "over-under"}


class PhotorealIdentityNegativeInventoryError(StashSourceError):
    pass


def _performer_ids(item: Mapping[str, Any]) -> set[str]:
    return {
        str(performer.get("id"))
        for performer in (item.get("performers") or [])
        if isinstance(performer, Mapping) and performer.get("id") is not None
    }


def co_performer_counts(target_performer_id: str, scenes: Sequence[Mapping[str, Any]]) -> Counter[str]:
    target = str(target_performer_id or "").strip()
    if not target:
        raise PhotorealIdentityNegativeInventoryError("target performer id is required")
    counts: Counter[str] = Counter()
    for scene in scenes:
        if not isinstance(scene, Mapping):
            raise PhotorealIdentityNegativeInventoryError("target scene inventory contains a non-object")
        ids = _performer_ids(scene)
        if target not in ids:
            raise PhotorealIdentityNegativeInventoryError("target scene lost target performer binding")
        for performer_id in ids - {target}:
            counts[performer_id] += 1
    return counts


def _source_key(record: Mapping[str, Any]) -> str:
    kind = record.get("kind")
    if kind == "video":
        return f"scene:{record['scene_id']}:{record['path']}"
    return f"image:{record['image_id']}:{record['path']}"


def _calibration_video_eligible(video: Mapping[str, Any]) -> bool:
    projection = str(video.get("projection") or "").strip().lower()
    stereo_layout = str(video.get("stereo_layout") or "").strip().lower()
    return projection in CALIBRATION_VIDEO_PROJECTIONS and stereo_layout in CALIBRATION_VIDEO_STEREO_LAYOUTS


def _negative_candidates(inventory: Mapping[str, Any]) -> list[dict[str, Any]]:
    performer_id = str(inventory.get("performer_id") or "").strip()
    performer_name = str(inventory.get("performer_name") or "")
    if not performer_id:
        raise PhotorealIdentityNegativeInventoryError("negative performer inventory has no performer_id")
    if inventory.get("format") != "bodyrig-photoreal-source-inventory" or inventory.get("version") != 1:
        raise PhotorealIdentityNegativeInventoryError("negative performer inventory format/version mismatch")
    if inventory.get("build_only") is not True or inventory.get("runtime_dependency") is not False:
        raise PhotorealIdentityNegativeInventoryError("negative performer inventory authority boundary is invalid")
    if inventory.get("production_activation") is not False:
        raise PhotorealIdentityNegativeInventoryError("negative performer inventory crossed production authority")

    result: list[dict[str, Any]] = []
    for video in inventory.get("videos") or []:
        if not isinstance(video, Mapping) or int(video.get("performer_count") or 0) != 1:
            continue
        if not _calibration_video_eligible(video):
            continue
        path = str(video.get("path") or "").strip()
        scene_id = str(video.get("scene_id") or "").strip()
        if not path or not scene_id:
            continue
        record = {
            "kind": "video",
            "scene_id": scene_id,
            "path": path,
            "information_score": float(video.get("information_score") or 0.0),
            "projection": str(video.get("projection") or "unknown"),
            "stereo_layout": str(video.get("stereo_layout") or "unknown"),
            "width": int(video.get("width") or 0),
            "height": int(video.get("height") or 0),
            "duration_seconds": float(video.get("duration_seconds") or 0.0),
            "frame_rate": float(video.get("frame_rate") or 0.0),
            "size_bytes": int(video.get("size_bytes") or 0),
            "subject_performer_id": performer_id,
            "subject_performer_name": performer_name,
            "source_binding": "scene-single-performer",
        }
        record["source_key"] = _source_key(record)
        result.append(record)

    for image in inventory.get("images") or []:
        if not isinstance(image, Mapping):
            continue
        if image.get("source_binding") != "direct-performer" or int(image.get("performer_count") or 0) != 1:
            continue
        path = str(image.get("path") or "").strip()
        image_id = str(image.get("image_id") or "").strip()
        if not path or not image_id:
            continue
        record = {
            "kind": "image",
            "image_id": image_id,
            "path": path,
            "information_score": float(image.get("information_score") or 0.0),
            "width": int(image.get("width") or 0),
            "height": int(image.get("height") or 0),
            "megapixels": float(image.get("megapixels") or 0.0),
            "size_bytes": int(image.get("size_bytes") or 0),
            "subject_performer_id": performer_id,
            "subject_performer_name": performer_name,
            "source_binding": "direct-performer",
        }
        record["source_key"] = _source_key(record)
        result.append(record)
    result.sort(key=lambda item: (-float(item["information_score"]), item["kind"], item["source_key"].casefold()))
    return result


def _select_diverse(candidates: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for kind in ("image", "video"):
        match = next((item for item in candidates if item["kind"] == kind), None)
        if match is not None and len(selected) < limit:
            selected.append(match)
    selected_keys = {item["source_key"] for item in selected}
    for item in candidates:
        if len(selected) >= limit:
            break
        if item["source_key"] not in selected_keys:
            selected.append(item)
            selected_keys.add(item["source_key"])
    return selected


def build_identity_negative_inventory(
    *,
    target_performer_id: str,
    target_scenes: Sequence[Mapping[str, Any]],
    negative_performer_inventories: Mapping[str, Mapping[str, Any]],
    max_negative_performers: int = DEFAULT_MAX_NEGATIVE_PERFORMERS,
    sources_per_performer: int = DEFAULT_SOURCES_PER_PERFORMER,
) -> dict[str, Any]:
    target = str(target_performer_id or "").strip()
    if not target:
        raise PhotorealIdentityNegativeInventoryError("target performer id is required")
    if isinstance(max_negative_performers, bool) or not 1 <= max_negative_performers <= MAX_NEGATIVE_PERFORMERS:
        raise PhotorealIdentityNegativeInventoryError("max_negative_performers is outside supported bounds")
    if isinstance(sources_per_performer, bool) or not 1 <= sources_per_performer <= MAX_SOURCES_PER_PERFORMER:
        raise PhotorealIdentityNegativeInventoryError("sources_per_performer is outside supported bounds")

    counts = co_performer_counts(target, target_scenes)
    ranked = sorted(counts, key=lambda performer_id: (-counts[performer_id], performer_id))
    if not ranked:
        raise PhotorealIdentityNegativeInventoryError("target performer has no co-performer evidence for negative calibration")

    sources: list[dict[str, Any]] = []
    selected_subjects: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for subject_id in ranked:
        if len(selected_subjects) >= max_negative_performers:
            break
        inventory = negative_performer_inventories.get(subject_id)
        if not isinstance(inventory, Mapping):
            continue
        if str(inventory.get("performer_id") or "").strip() != subject_id:
            raise PhotorealIdentityNegativeInventoryError("negative performer inventory identity mismatch")
        if subject_id == target:
            raise PhotorealIdentityNegativeInventoryError("target performer cannot enter negative calibration inventory")
        candidates = _negative_candidates(inventory)
        chosen = _select_diverse(candidates, sources_per_performer)
        if not chosen:
            continue
        for item in chosen:
            path_key = str(item["path"]).casefold()
            if path_key in seen_paths:
                raise PhotorealIdentityNegativeInventoryError("negative calibration source path is duplicated")
            seen_paths.add(path_key)
            record = dict(item)
            record["target_performer_id"] = target
            record["target_performer_absent"] = True
            record["label_authority"] = LABEL_AUTHORITY
            sources.append(record)
        selected_subjects.append(
            {
                "performer_id": subject_id,
                "performer_name": str(inventory.get("performer_name") or ""),
                "cooccurrence_scene_count": int(counts[subject_id]),
                "selected_source_count": len(chosen),
            }
        )

    if not sources:
        raise PhotorealIdentityNegativeInventoryError("no source-authoritative negative calibration media was found")
    sources.sort(key=lambda item: (item["subject_performer_id"], -float(item["information_score"]), item["source_key"]))
    selected_subjects.sort(key=lambda item: (-int(item["cooccurrence_scene_count"]), item["performer_id"]))
    return {
        "format": FORMAT,
        "version": VERSION,
        "target_performer_id": target,
        "label_authority": LABEL_AUTHORITY,
        "negative_performer_count": len(selected_subjects),
        "source_count": len(sources),
        "negative_performers": selected_subjects,
        "sources": sources,
        "calibration_only": True,
        "photoreal_teacher_input": False,
        "teacher_training_authorized": False,
        "identity_matching_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def fetch_identity_negative_inventory(
    client: StashClient,
    target_performer_id: str,
    *,
    max_negative_performers: int = DEFAULT_MAX_NEGATIVE_PERFORMERS,
    sources_per_performer: int = DEFAULT_SOURCES_PER_PERFORMER,
    page_size: int = DEFAULT_PAGE_SIZE,
    maximum_items: int = 100_000,
) -> dict[str, Any]:
    target = str(target_performer_id or "").strip()
    if not target:
        raise PhotorealIdentityNegativeInventoryError("target performer id is required")
    target_scenes_result = fetch_exhaustive_performer_scenes(
        client,
        target,
        page_size=page_size,
        maximum_scenes=maximum_items,
    )
    counts = co_performer_counts(target, target_scenes_result.scenes)
    ranked = sorted(counts, key=lambda performer_id: (-counts[performer_id], performer_id))
    inventories: dict[str, Mapping[str, Any]] = {}
    eligible_inventory_count = 0
    for performer_id in ranked:
        try:
            inventory = fetch_photoreal_source_inventory(
                client,
                performer_id,
                page_size=page_size,
                maximum_items=maximum_items,
            )
        except PhotorealStashInventoryError:
            continue
        inventories[performer_id] = inventory
        if _negative_candidates(inventory):
            eligible_inventory_count += 1
            if eligible_inventory_count >= max_negative_performers:
                break
    return build_identity_negative_inventory(
        target_performer_id=target,
        target_scenes=target_scenes_result.scenes,
        negative_performer_inventories=inventories,
        max_negative_performers=max_negative_performers,
        sources_per_performer=sources_per_performer,
    )
