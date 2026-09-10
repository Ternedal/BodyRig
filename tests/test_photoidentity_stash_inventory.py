from __future__ import annotations

import pytest

from bodyrig.photoidentity_stash_inventory import (
    PhotoIdentityStashInventoryError,
    fetch_exhaustive_performer_scenes,
)
from bodyrig.stash_source import StashClient, StashConfig, StashGraphQLError


def _scene(index: int, performers: tuple[str, ...] = ("42",)) -> dict:
    return {
        "id": str(index),
        "title": f"Scene {index}",
        "files": [],
        "tags": [],
        "performers": [{"id": value, "name": f"P{value}"} for value in performers],
    }


def test_inventory_paginates_to_exact_server_count() -> None:
    scenes = [_scene(index) for index in range(1, 6)]
    calls: list[dict] = []

    def transport(query: str, variables: dict) -> dict:
        calls.append(dict(variables))
        page = int(variables["page"])
        limit = int(variables["limit"])
        start = (page - 1) * limit
        return {"findScenes": {"count": len(scenes), "scenes": scenes[start : start + limit]}}

    client = StashClient(StashConfig("http://localhost:9999"), transport=transport)
    result = fetch_exhaustive_performer_scenes(client, "42", page_size=2)

    assert result.total_count == 5
    assert result.page_count == 3
    assert result.page_size == 2
    assert result.schema == "current"
    assert [item["id"] for item in result.scenes] == ["1", "2", "3", "4", "5"]
    assert [item["page"] for item in calls] == [1, 2, 3]


def test_inventory_uses_legacy_schema_for_entire_pagination_after_current_schema_rejection() -> None:
    scenes = [_scene(index) for index in range(1, 4)]
    schemas: list[str] = []

    def transport(query: str, variables: dict) -> dict:
        if "performers: {value:" in query:
            schemas.append("current")
            raise StashGraphQLError("unknown field performers")
        schemas.append("legacy")
        page = int(variables["page"])
        start = (page - 1) * 2
        return {"findScenes": {"count": 3, "scenes": scenes[start : start + 2]}}

    client = StashClient(StashConfig("http://localhost:9999"), transport=transport)
    result = fetch_exhaustive_performer_scenes(client, "42", page_size=2)

    assert result.schema == "legacy"
    assert schemas == ["current", "legacy", "legacy"]


def test_inventory_fails_if_count_changes_between_pages() -> None:
    scenes = [_scene(index) for index in range(1, 5)]

    def transport(query: str, variables: dict) -> dict:
        page = int(variables["page"])
        count = 4 if page == 1 else 5
        start = (page - 1) * 2
        return {"findScenes": {"count": count, "scenes": scenes[start : start + 2]}}

    client = StashClient(StashConfig("http://localhost:9999"), transport=transport)
    with pytest.raises(PhotoIdentityStashInventoryError, match="count changed"):
        fetch_exhaustive_performer_scenes(client, "42", page_size=2)


def test_inventory_fails_on_duplicate_scene_across_pages() -> None:
    pages = {1: [_scene(1), _scene(2)], 2: [_scene(2), _scene(3)]}

    def transport(query: str, variables: dict) -> dict:
        return {"findScenes": {"count": 4, "scenes": pages[int(variables["page"])]}}

    client = StashClient(StashConfig("http://localhost:9999"), transport=transport)
    with pytest.raises(PhotoIdentityStashInventoryError, match="repeated scene 2"):
        fetch_exhaustive_performer_scenes(client, "42", page_size=2)


def test_inventory_fails_if_server_result_loses_requested_performer_binding() -> None:
    def transport(query: str, variables: dict) -> dict:
        return {"findScenes": {"count": 1, "scenes": [_scene(1, performers=("99",))]}}

    client = StashClient(StashConfig("http://localhost:9999"), transport=transport)
    with pytest.raises(PhotoIdentityStashInventoryError, match="lost requested performer binding"):
        fetch_exhaustive_performer_scenes(client, "42")


def test_inventory_fails_closed_above_explicit_safety_bound() -> None:
    def transport(query: str, variables: dict) -> dict:
        return {"findScenes": {"count": 10001, "scenes": []}}

    client = StashClient(StashConfig("http://localhost:9999"), transport=transport)
    with pytest.raises(PhotoIdentityStashInventoryError, match="above the explicit safety bound"):
        fetch_exhaustive_performer_scenes(client, "42", maximum_scenes=10000)


def test_inventory_rejects_short_nonfinal_page() -> None:
    def transport(query: str, variables: dict) -> dict:
        page = int(variables["page"])
        values = [_scene(1)] if page == 1 else [_scene(2), _scene(3)]
        return {"findScenes": {"count": 4, "scenes": values}}

    client = StashClient(StashConfig("http://localhost:9999"), transport=transport)
    with pytest.raises(PhotoIdentityStashInventoryError, match="ended early"):
        fetch_exhaustive_performer_scenes(client, "42", page_size=2)
