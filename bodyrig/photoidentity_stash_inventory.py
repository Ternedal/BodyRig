from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .stash_source import StashClient, StashGraphQLError, StashSourceError


DEFAULT_PAGE_SIZE = 250
MAX_PAGE_SIZE = 1000
MAX_SCENE_SAFETY_BOUND = 100_000


class PhotoIdentityStashInventoryError(StashSourceError):
    pass


@dataclass(frozen=True)
class PerformerSceneInventory:
    scenes: tuple[dict[str, Any], ...]
    total_count: int
    page_count: int
    page_size: int
    schema: str


def _query(schema: str, scene_fields: str) -> str:
    if schema == "current":
        scene_filter = "scene_filter: {performers: {value: [$id], modifier: INCLUDES}}"
        operation = "BodyRigPhotoidentityPerformerScenes"
    elif schema == "legacy":
        scene_filter = "scene_filter: {performer_id: $id}"
        operation = "BodyRigPhotoidentityPerformerScenesLegacy"
    else:  # pragma: no cover - internal programming error
        raise AssertionError(f"unsupported Stash schema: {schema}")
    return f"""
query {operation}($id: ID!, $page: Int!, $limit: Int!) {{
  findScenes(
    {scene_filter}
    filter: {{page: $page, per_page: $limit, sort: "created_at", direction: DESC}}
  ) {{
    count
    scenes {{ {scene_fields} }}
  }}
}}
"""


def _page(
    client: StashClient,
    *,
    performer_id: str,
    schema: str,
    page: int,
    page_size: int,
) -> tuple[int, list[dict[str, Any]]]:
    data = client._graphql(  # noqa: SLF001 - same package, exact Stash transport authority
        _query(schema, client._scene_fields()),  # noqa: SLF001
        {"id": performer_id, "page": page, "limit": page_size},
    )
    result = data.get("findScenes")
    if not isinstance(result, Mapping):
        raise PhotoIdentityStashInventoryError("Stash performer scene inventory has no findScenes object")
    count = result.get("count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise PhotoIdentityStashInventoryError("Stash performer scene inventory returned an invalid total count")
    raw_scenes = result.get("scenes")
    if not isinstance(raw_scenes, list):
        raise PhotoIdentityStashInventoryError("Stash performer scene inventory returned an invalid scene list")
    scenes: list[dict[str, Any]] = []
    for raw in raw_scenes:
        if not isinstance(raw, Mapping):
            raise PhotoIdentityStashInventoryError("Stash performer scene inventory returned a non-object scene")
        scene_id = str(raw.get("id") or "").strip()
        if not scene_id:
            raise PhotoIdentityStashInventoryError("Stash performer scene inventory returned a scene without id")
        scenes.append(dict(raw))
    return count, scenes


def fetch_exhaustive_performer_scenes(
    client: StashClient,
    performer_id: str,
    *,
    page_size: int = DEFAULT_PAGE_SIZE,
    maximum_scenes: int = 10_000,
) -> PerformerSceneInventory:
    """Fetch a stable, count-bound performer scene universe from Stash.

    Exhaustion is authority, not a guess: every server-advertised scene must be
    retrieved exactly once, the advertised count must remain stable on every
    page, and every returned scene must still bind the requested performer in
    its explicit performer list. A changing library or duplicate/omitted page
    therefore fails closed and can be retried later.
    """

    performer_id = str(performer_id or "").strip()
    if not performer_id or len(performer_id) > 256:
        raise PhotoIdentityStashInventoryError("photoidentity performer id is invalid")
    if isinstance(page_size, bool) or not 1 <= page_size <= MAX_PAGE_SIZE:
        raise PhotoIdentityStashInventoryError(f"Stash inventory page_size must be in 1..{MAX_PAGE_SIZE}")
    if isinstance(maximum_scenes, bool) or not 1 <= maximum_scenes <= MAX_SCENE_SAFETY_BOUND:
        raise PhotoIdentityStashInventoryError(
            f"Stash inventory maximum_scenes must be in 1..{MAX_SCENE_SAFETY_BOUND}"
        )

    schema = "current"
    try:
        total, first = _page(
            client,
            performer_id=performer_id,
            schema=schema,
            page=1,
            page_size=page_size,
        )
    except StashGraphQLError as current_error:
        schema = "legacy"
        try:
            total, first = _page(
                client,
                performer_id=performer_id,
                schema=schema,
                page=1,
                page_size=page_size,
            )
        except StashGraphQLError as legacy_error:
            raise PhotoIdentityStashInventoryError(
                "Stash exhaustive performer scene inventory failed for current and legacy schemas: "
                f"{current_error}; {legacy_error}"
            ) from legacy_error

    if total > maximum_scenes:
        raise PhotoIdentityStashInventoryError(
            f"Stash performer has {total} scenes, above the explicit safety bound {maximum_scenes}; "
            "refusing to claim source-universe exhaustion"
        )
    if total == 0:
        if first:
            raise PhotoIdentityStashInventoryError("Stash inventory count is zero but page one returned scenes")
        return PerformerSceneInventory((), 0, 1, page_size, schema)

    expected_pages = (total + page_size - 1) // page_size
    all_scenes: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def accept_page(page_number: int, scenes: list[dict[str, Any]]) -> None:
        if page_number < expected_pages and len(scenes) != page_size:
            raise PhotoIdentityStashInventoryError(
                f"Stash scene inventory page {page_number} ended early; source universe is unstable"
            )
        for scene in scenes:
            scene_id = str(scene["id"])
            if scene_id in seen_ids:
                raise PhotoIdentityStashInventoryError(
                    f"Stash scene inventory repeated scene {scene_id}; refusing ambiguous pagination"
                )
            performer_ids = {
                str(item.get("id"))
                for item in (scene.get("performers") or [])
                if isinstance(item, Mapping) and item.get("id") is not None
            }
            if performer_id not in performer_ids:
                raise PhotoIdentityStashInventoryError(
                    f"Stash scene {scene_id} lost requested performer binding during inventory"
                )
            seen_ids.add(scene_id)
            all_scenes.append(scene)

    accept_page(1, first)
    for page_number in range(2, expected_pages + 1):
        observed_total, scenes = _page(
            client,
            performer_id=performer_id,
            schema=schema,
            page=page_number,
            page_size=page_size,
        )
        if observed_total != total:
            raise PhotoIdentityStashInventoryError(
                f"Stash performer scene count changed during exhaustive inventory: {total} -> {observed_total}"
            )
        accept_page(page_number, scenes)

    if len(all_scenes) != total:
        raise PhotoIdentityStashInventoryError(
            f"Stash exhaustive inventory returned {len(all_scenes)}/{total} unique scenes"
        )
    return PerformerSceneInventory(tuple(all_scenes), total, expected_pages, page_size, schema)
