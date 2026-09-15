from __future__ import annotations

import json
from pathlib import Path

import pytest

from bodyrig.photoreal_source_verify import (
    PhotorealSourceVerifyError,
    verify_inventory_file,
    verify_inventory_sources,
)


def _inventory() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "video_file_count": 1,
        "image_file_count": 1,
        "summary": {"source_universe_exhaustive": True},
        "videos": [
            {"scene_id": "s1", "path": r"E:\VR\source.mp4", "size_bytes": 100},
        ],
        "images": [
            {"image_id": "i1", "path": r"F:\VR\source.jpg", "size_bytes": 50},
        ],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _verify_rejects(inventory: dict[str, object], message: str | None = None) -> None:
    context = pytest.raises(PhotorealSourceVerifyError, match=message) if message else pytest.raises(PhotorealSourceVerifyError)
    with context:
        verify_inventory_sources(
            inventory,
            path_mapping={},
            exists_file=lambda _path: True,
            file_size=lambda _path: 1,
            hash_file=lambda _path: "a" * 64,
        )


def test_point_of_use_requires_exhaustive_source_universe() -> None:
    inventory = _inventory()
    inventory["summary"] = {"source_universe_exhaustive": False}
    _verify_rejects(inventory, "not exhaustive")


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("video_file_count", True, "video_file_count mismatch"),
        ("video_file_count", 2, "video_file_count mismatch"),
        ("image_file_count", "1", "image_file_count mismatch"),
        ("performer_name", True, "performer_name is invalid"),
    ],
)
def test_point_of_use_rejects_header_type_or_count_confusion(
    field: str,
    value: object,
    message: str,
) -> None:
    inventory = _inventory()
    inventory[field] = value
    _verify_rejects(inventory, message)


@pytest.mark.parametrize(
    ("key", "field", "value"),
    [
        ("videos", "scene_id", True),
        ("videos", "path", True),
        ("images", "image_id", 1),
        ("images", "path", 1),
        ("videos", "size_bytes", "100"),
        ("images", "size_bytes", 50.0),
    ],
)
def test_point_of_use_rejects_source_field_type_confusion(key: str, field: str, value: object) -> None:
    inventory = _inventory()
    values = inventory[key]
    assert isinstance(values, list)
    item = dict(values[0])
    item[field] = value
    inventory[key] = [item]
    _verify_rejects(inventory)


def test_direct_local_proof_source_count_must_match_inventory(tmp_path: Path) -> None:
    inventory_path = tmp_path / "inventory.json"
    path_map_path = tmp_path / "path-map.json"
    inventory_path.write_text(json.dumps(_inventory()), encoding="utf-8")
    path_map_path.write_text(
        json.dumps(
            {
                "format": "bodyrig-photoreal-direct-path-proof",
                "version": 1,
                "transport_mode": "direct-local",
                "stash_origin": "http://localhost:9999",
                "stash_host": "localhost",
                "performer_ids": ["42"],
                "source_count": 1,
                "all_sources_directly_readable": True,
                "mapping": {},
                "proof": [],
                "build_only": True,
                "runtime_dependency": False,
                "production_activation": False,
                "updated_utc": "2026-09-15T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PhotorealSourceVerifyError, match="source count does not match inventory"):
        verify_inventory_file(
            inventory_path,
            path_map_path,
            tmp_path / "receipt.json",
            stash_url="http://localhost:9999",
        )
