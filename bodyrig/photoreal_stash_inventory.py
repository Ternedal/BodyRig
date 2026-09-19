from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

from .photoidentity_stash_inventory import fetch_exhaustive_performer_scenes
from .stash_source import StashClient, StashGraphQLError, StashSourceError

FORMAT = "bodyrig-photoreal-source-inventory"
VERSION = 1
DEFAULT_PAGE_SIZE = 250
MAX_PAGE_SIZE = 1000
MAX_ITEM_SAFETY_BOUND = 100_000


class PhotorealStashInventoryError(StashSourceError):
    pass


@dataclass(frozen=True)
class _PagedResult:
    items: tuple[dict[str, Any], ...]
    total_count: int
    page_count: int


def _number(value: Any) -> float:
    try:
        parsed = float(value or 0)
    except (TypeError, ValueError):
        return 0.0
    return parsed if math.isfinite(parsed) and parsed >= 0 else 0.0


def _int(value: Any) -> int:
    parsed = int(_number(value))
    return parsed if parsed >= 0 else 0


def _tags(item: Mapping[str, Any]) -> list[str]:
    return sorted(
        {
            str(tag.get("name") or "").strip()
            for tag in (item.get("tags") or [])
            if isinstance(tag, Mapping) and str(tag.get("name") or "").strip()
        },
        key=str.lower,
    )


def _performer_ids(item: Mapping[str, Any]) -> set[str]:
    return {
        str(performer.get("id"))
        for performer in (item.get("performers") or [])
        if isinstance(performer, Mapping) and performer.get("id") is not None
    }


def _projection_metadata(tags: Iterable[str], *, width: int, height: int) -> tuple[str, str]:
    normalized = " ".join(
        str(tag)
        .lower()
        .replace("_", " ")
        .replace("-", " ")
        .replace("°", " degree ")
        for tag in tags
    )
    compact = "".join(normalized.split())
    words = set(normalized.split())

    if "sidebyside" in compact or "sbs" in words:
        stereo_layout = "side-by-side"
    elif "overunder" in compact or "topbottom" in compact or "ou" in words:
        stereo_layout = "over-under"
    elif (
        "stereo" in words
        or "stereoscopic" in compact
        or "3d" in words
        or "3davailable" in compact
    ):
        stereo_layout = "stereo-unknown"
    else:
        stereo_layout = "mono"

    if (
        "vr180" in compact
        or "180degree" in compact
        or "180degrees" in compact
    ):
        projection = "vr180"
    elif "vr360" in compact or "360vr" in compact:
        projection = "vr360"
    elif "equirectangular" in compact or "panorama" in compact or "panoramic" in compact:
        projection = "equirectangular"
    elif width > 0 and height > 0 and 1.95 <= width / height <= 2.05:
        projection = "projection-ambiguous-2to1"
    else:
        projection = "flat"

    if projection == "projection-ambiguous-2to1" and stereo_layout == "mono":
        stereo_layout = "unknown"
    return projection, stereo_layout


def _video_score(
    *,
    width: int,
    height: int,
    duration: float,
    fps: float,
    performer_count: int,
    projection: str,
    stereo_layout: str,
) -> float:
    megapixels = (width * height) / 1_000_000.0
    score = min(megapixels, 40.0) * 10.0
    if height >= 4320:
        score += 90.0
    elif height >= 2880:
        score += 65.0
    elif height >= 2160:
        score += 45.0
    elif height >= 1440:
        score += 25.0
    if fps >= 60:
        score += 18.0
    elif fps >= 50:
        score += 14.0
    elif fps >= 24:
        score += 8.0
    if performer_count == 1:
        score += 60.0
    elif performer_count > 1:
        score -= min(40.0, 8.0 * (performer_count - 1))
    if projection != "flat" or stereo_layout != "mono":
        score += 35.0
    if 30.0 <= duration <= 7200.0:
        score += 12.0
    return round(score, 3)


def _image_score(*, width: int, height: int, performer_count: int, source_binding: str) -> float:
    megapixels = (width * height) / 1_000_000.0
    score = min(megapixels, 100.0) * 12.0
    if min(width, height) >= 4000:
        score += 80.0
    elif min(width, height) >= 3000:
        score += 55.0
    elif min(width, height) >= 2000:
        score += 30.0
    if performer_count == 1:
        score += 55.0
    if source_binding == "direct-performer":
        score += 15.0
    return round(score, 3)


def _fetch_paged(
    client: StashClient,
    *,
    query: str,
    root_key: str,
    items_key: str,
    variables: Mapping[str, Any],
    page_size: int,
    maximum_items: int,
) -> _PagedResult:
    if isinstance(page_size, bool) or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise PhotorealStashInventoryError(f"page_size must be in 1..{MAX_PAGE_SIZE}")
    if isinstance(maximum_items, bool) or not 1 <= maximum_items <= MAX_ITEM_SAFETY_BOUND:
        raise PhotorealStashInventoryError(f"maximum_items must be in 1..{MAX_ITEM_SAFETY_BOUND}")

    page = 1
    expected_total: int | None = None
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    while True:
        payload = dict(variables)
        payload.update({"page": page, "limit": page_size})
        data = client._graphql(query, payload)  # noqa: SLF001
        root = data.get(root_key)
        if not isinstance(root, Mapping):
            raise PhotorealStashInventoryError(f"Stash {root_key} result is missing")
        total = root.get("count")
        if isinstance(total, bool) or not isinstance(total, int) or total < 0:
            raise PhotorealStashInventoryError(f"Stash {root_key} count is invalid")
        if total > maximum_items:
            raise PhotorealStashInventoryError(
                f"Stash {root_key} count {total} exceeds safety bound {maximum_items}"
            )
        if expected_total is None:
            expected_total = total
        elif total != expected_total:
            raise PhotorealStashInventoryError(
                f"Stash {root_key} count changed during inventory: {expected_total} -> {total}"
            )

        raw_items = root.get(items_key)
        if not isinstance(raw_items, list):
            raise PhotorealStashInventoryError(f"Stash {root_key}.{items_key} is invalid")
        for raw in raw_items:
            if not isinstance(raw, Mapping):
                raise PhotorealStashInventoryError(f"Stash {root_key} returned a non-object")
            item_id = str(raw.get("id") or "").strip()
            if not item_id:
                raise PhotorealStashInventoryError(f"Stash {root_key} item has no id")
            if item_id in seen_ids:
                raise PhotorealStashInventoryError(f"Stash {root_key} repeated id {item_id}")
            seen_ids.add(item_id)
            items.append(dict(raw))

        if len(items) >= total:
            break
        if not raw_items:
            raise PhotorealStashInventoryError(f"Stash {root_key} pagination ended early")
        page += 1

    if expected_total is None or len(items) != expected_total:
        raise PhotorealStashInventoryError(
            f"Stash {root_key} inventory returned {len(items)}/{expected_total or 0} unique items"
        )
    return _PagedResult(tuple(items), expected_total, page)


def _image_query(filter_expression: str) -> str:
    return f"""
query BodyRigPhotorealImages($id: ID!, $page: Int!, $limit: Int!) {{
  findImages(
    image_filter: {{{filter_expression}}}
    filter: {{page: $page, per_page: $limit, sort: "created_at", direction: DESC}}
  ) {{
    count
    images {{
      id title date details photographer
      visual_files {{
        __typename
        ... on ImageFile {{ id path basename width height size format }}
      }}
      tags {{ name }}
      performers {{ id name }}
      galleries {{ id title performers {{ id }} }}
    }}
  }}
}}
"""


def _gallery_query() -> str:
    return """
query BodyRigPhotorealGalleries($id: ID!, $page: Int!, $limit: Int!) {
  findGalleries(
    gallery_filter: {performers: {value: [$id], modifier: INCLUDES}}
    filter: {page: $page, per_page: $limit, sort: "created_at", direction: DESC}
  ) {
    count
    galleries {
      id title date details photographer image_count
      files { id path basename size }
      tags { name }
      performers { id name }
    }
  }
}
"""


def fetch_photoreal_source_inventory(
    client: StashClient,
    performer_id: str,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    maximum_items: int = 100_000,
) -> dict[str, Any]:
    performer_id = str(performer_id or "").strip()
    if not performer_id:
        raise PhotorealStashInventoryError("performer id is required")

    performer = client.performer(performer_id)
    stash_version = client.version()
    scenes = fetch_exhaustive_performer_scenes(
        client,
        performer_id,
        page_size=page_size,
        maximum_scenes=maximum_items,
    )

    try:
        direct_images = _fetch_paged(
            client,
            query=_image_query("performers: {value: [$id], modifier: INCLUDES}"),
            root_key="findImages",
            items_key="images",
            variables={"id": performer_id},
            page_size=page_size,
            maximum_items=maximum_items,
        )
        galleries = _fetch_paged(
            client,
            query=_gallery_query(),
            root_key="findGalleries",
            items_key="galleries",
            variables={"id": performer_id},
            page_size=page_size,
            maximum_items=maximum_items,
        )
    except StashGraphQLError as exc:
        raise PhotorealStashInventoryError(
            "Stash image/gallery inventory requires a current Stash GraphQL schema"
        ) from exc

    gallery_ids = [str(item["id"]) for item in galleries.items]
    gallery_image_map: dict[str, dict[str, Any]] = {}
    for gallery_id in gallery_ids:
        result = _fetch_paged(
            client,
            query=_image_query("galleries: {value: [$id], modifier: INCLUDES}"),
            root_key="findImages",
            items_key="images",
            variables={"id": gallery_id},
            page_size=page_size,
            maximum_items=maximum_items,
        )
        for item in result.items:
            gallery_image_map[str(item["id"])] = item

    direct_ids = {str(item["id"]) for item in direct_images.items}
    all_images: dict[str, dict[str, Any]] = {str(item["id"]): item for item in direct_images.items}
    all_images.update(gallery_image_map)

    videos: list[dict[str, Any]] = []
    for scene in scenes.scenes:
        performer_ids = _performer_ids(scene)
        if performer_id not in performer_ids:
            raise PhotorealStashInventoryError(f"scene {scene.get('id')} lost performer binding")
        tags = _tags(scene)
        performer_count = len(performer_ids)
        for file_info in scene.get("files") or []:
            if not isinstance(file_info, Mapping):
                continue
            path = str(file_info.get("path") or "").strip()
            if not path:
                continue
            width = _int(file_info.get("width"))
            height = _int(file_info.get("height"))
            duration = _number(file_info.get("duration"))
            fps = _number(file_info.get("frame_rate"))
            projection, stereo_layout = _projection_metadata(tags, width=width, height=height)
            videos.append(
                {
                    "scene_id": str(scene["id"]),
                    "scene_title": str(scene.get("title") or ""),
                    "path": path,
                    "width": width,
                    "height": height,
                    "duration_seconds": round(duration, 3),
                    "frame_rate": round(fps, 3),
                    "video_codec": str(file_info.get("video_codec") or ""),
                    "size_bytes": _int(file_info.get("size")),
                    "performer_count": performer_count,
                    "projection": projection,
                    "stereo_layout": stereo_layout,
                    "tags": tags,
                    "information_score": _video_score(
                        width=width,
                        height=height,
                        duration=duration,
                        fps=fps,
                        performer_count=performer_count,
                        projection=projection,
                        stereo_layout=stereo_layout,
                    ),
                }
            )

    images: list[dict[str, Any]] = []
    for image_id, image in all_images.items():
        direct = image_id in direct_ids
        gallery_bindings = [
            str(gallery.get("id"))
            for gallery in (image.get("galleries") or [])
            if isinstance(gallery, Mapping)
            and performer_id in _performer_ids(gallery)
            and gallery.get("id") is not None
        ]
        performer_ids = _performer_ids(image)
        if not direct and not gallery_bindings:
            raise PhotorealStashInventoryError(f"image {image_id} lacks performer/gallery binding")
        source_binding = "direct-performer" if direct else "performer-gallery"
        tags = _tags(image)
        performer_count = len(performer_ids)
        for file_info in image.get("visual_files") or []:
            if not isinstance(file_info, Mapping) or file_info.get("__typename") != "ImageFile":
                continue
            path = str(file_info.get("path") or "").strip()
            if not path:
                continue
            width = _int(file_info.get("width"))
            height = _int(file_info.get("height"))
            images.append(
                {
                    "image_id": image_id,
                    "title": str(image.get("title") or ""),
                    "path": path,
                    "width": width,
                    "height": height,
                    "megapixels": round((width * height) / 1_000_000.0, 3),
                    "size_bytes": _int(file_info.get("size")),
                    "format": str(file_info.get("format") or ""),
                    "performer_count": performer_count,
                    "source_binding": source_binding,
                    "gallery_ids": sorted(set(gallery_bindings)),
                    "tags": tags,
                    "information_score": _image_score(
                        width=width,
                        height=height,
                        performer_count=performer_count,
                        source_binding=source_binding,
                    ),
                }
            )

    gallery_records = [
        {
            "gallery_id": str(gallery["id"]),
            "title": str(gallery.get("title") or ""),
            "image_count": _int(gallery.get("image_count")),
            "performer_count": len(_performer_ids(gallery)),
            "tags": _tags(gallery),
            "files": [
                {
                    "path": str(file_info.get("path") or ""),
                    "basename": str(file_info.get("basename") or ""),
                    "size_bytes": _int(file_info.get("size")),
                }
                for file_info in (gallery.get("files") or [])
                if isinstance(file_info, Mapping)
            ],
        }
        for gallery in galleries.items
    ]

    videos.sort(key=lambda item: (-float(item["information_score"]), str(item["path"]).lower()))
    images.sort(key=lambda item: (-float(item["information_score"]), str(item["path"]).lower()))
    gallery_records.sort(key=lambda item: str(item["gallery_id"]))

    flat_seconds = sum(
        float(item["duration_seconds"])
        for item in videos
        if item["projection"] == "flat" and item["stereo_layout"] == "mono"
    )
    spatial_seconds = sum(
        float(item["duration_seconds"])
        for item in videos
        if item["projection"] != "flat" or item["stereo_layout"] != "mono"
    )
    high_res_images = sum(1 for item in images if max(int(item["width"]), int(item["height"])) >= 3840)
    total_still_megapixels = sum(float(item["megapixels"]) for item in images)

    return {
        "format": FORMAT,
        "version": VERSION,
        "performer_id": performer_id,
        "performer_name": performer["name"],
        "performer": {
            "id": performer_id,
            "name": performer["name"],
            "disambiguation": performer.get("disambiguation", ""),
        },
        "stash_version": stash_version,
        "scene_count": scenes.total_count,
        "gallery_count": galleries.total_count,
        "image_count": len(all_images),
        "video_file_count": len(videos),
        "image_file_count": len(images),
        "summary": {
            "flat_video_hours": round(flat_seconds / 3600.0, 3),
            "spatial_or_projection_video_hours": round(spatial_seconds / 3600.0, 3),
            "high_resolution_image_count": high_res_images,
            "total_still_megapixels": round(total_still_megapixels, 3),
            "source_universe_exhaustive": True,
        },
        "videos": videos,
        "images": images,
        "galleries": gallery_records,
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def write_inventory(path: str | Path, inventory: Mapping[str, Any]) -> Path:
    output = Path(path).expanduser().resolve()
    if output.exists():
        raise PhotorealStashInventoryError(f"inventory output already exists: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(dict(inventory), indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return output
