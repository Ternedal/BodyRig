from __future__ import annotations

from datetime import datetime, timezone

import pytest

from bodyrig.photoreal_inventory_path_map import (
    PhotorealInventoryPathMapError,
    build_inventory_path_map,
)
from bodyrig.photoreal_source_verify import translate_stash_path
from bodyrig.stash_path_cache import validate_cache


def _inventory() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "video_file_count": 2,
        "image_file_count": 1,
        "summary": {"source_universe_exhaustive": True},
        "videos": [
            {"scene_id": "old", "path": r"E:\VR\archive\old.mp4"},
            {"scene_id": "new", "path": r"E:\VR\current\new.mp4"},
        ],
        "images": [
            {"image_id": "still-only-drive", "path": r"F:\Photos\performer42.jpg"},
        ],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _filesystem() -> tuple[set[str], set[str]]:
    directories = {r"\\stashbox\VR_E", r"\\stashbox\VR_F"}
    files = {
        r"\\stashbox\VR_E\archive\old.mp4",
        r"\\stashbox\VR_E\current\new.mp4",
        r"\\stashbox\VR_F\performer42.jpg",
    }
    return directories, files


def test_builder_covers_exact_video_and_image_inventory() -> None:
    directories, files = _filesystem()
    now = datetime(2026, 9, 15, 11, 0, tzinfo=timezone.utc)

    result = build_inventory_path_map(
        _inventory(),
        stash_url="http://stashbox:9999",
        is_dir=lambda value: value in directories,
        is_file=lambda value: value in files,
        now=now,
    )

    assert result["performer_ids"] == ["42"]
    assert result["mapping"] == {
        r"E:\VR": r"\\stashbox\VR_E",
        r"F:\Photos": r"\\stashbox\VR_F",
    }
    assert len(result["proof"]) == 2
    assert {item["verified_files"] for item in result["proof"]} == {1, 2}

    inventory_paths = [
        r"E:\VR\archive\old.mp4",
        r"E:\VR\current\new.mp4",
        r"F:\Photos\performer42.jpg",
    ]
    assert {translate_stash_path(path, result["mapping"]) for path in inventory_paths} == files

    validated = validate_cache(
        result,
        stash_url="http://stashbox:9999",
        performer_ids=["42"],
        now=now,
        is_dir=lambda value: value in directories,
    )
    assert validated["ok"] is True
    assert validated["mapping"] == result["mapping"]


def test_builder_fails_if_one_exhaustive_inventory_source_is_unreadable() -> None:
    directories, files = _filesystem()
    files.remove(r"\\stashbox\VR_E\archive\old.mp4")

    with pytest.raises(PhotorealInventoryPathMapError, match="exhaustive source path is not readable"):
        build_inventory_path_map(
            _inventory(),
            stash_url="http://stashbox:9999",
            is_dir=lambda value: value in directories,
            is_file=lambda value: value in files,
        )


def test_builder_requires_image_only_drive_share() -> None:
    directories, files = _filesystem()
    directories.remove(r"\\stashbox\VR_F")

    with pytest.raises(PhotorealInventoryPathMapError, match="canonical Stash SMB share is not readable for F:"):
        build_inventory_path_map(
            _inventory(),
            stash_url="http://stashbox:9999",
            is_dir=lambda value: value in directories,
            is_file=lambda value: value in files,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("version", True),
        ("build_only", 1),
        ("photoreal_teacher_input", "true"),
        ("runtime_dependency", 0),
        ("production_activation", 0),
    ],
)
def test_builder_rejects_inventory_authority_type_confusion(field: str, value: object) -> None:
    inventory = _inventory()
    inventory[field] = value
    directories, files = _filesystem()

    with pytest.raises(PhotorealInventoryPathMapError):
        build_inventory_path_map(
            inventory,
            stash_url="http://stashbox:9999",
            is_dir=lambda path: path in directories,
            is_file=lambda path: path in files,
        )


def test_builder_rejects_false_exhaustive_summary() -> None:
    inventory = _inventory()
    inventory["summary"] = {"source_universe_exhaustive": False}
    directories, files = _filesystem()

    with pytest.raises(PhotorealInventoryPathMapError, match="not exhaustive"):
        build_inventory_path_map(
            inventory,
            stash_url="http://stashbox:9999",
            is_dir=lambda path: path in directories,
            is_file=lambda path: path in files,
        )
