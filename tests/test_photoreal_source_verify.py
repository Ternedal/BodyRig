from __future__ import annotations

from pathlib import Path

import pytest

from bodyrig.photoreal_source_verify import (
    PhotorealSourceVerifyError,
    translate_stash_path,
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
            {
                "scene_id": "s1",
                "path": "E:/VR/source.mp4",
                "size_bytes": 100,
            }
        ],
        "images": [
            {
                "image_id": "i1",
                "path": "F:/VR/source.jpg",
                "size_bytes": 50,
            }
        ],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_translate_remote_stash_drive_to_verified_share() -> None:
    mapping = {"E:": r"\\192.168.1.21\VR_E", "F:": r"\\192.168.1.21\VR_F"}
    assert translate_stash_path("E:/VR/a.mp4", mapping) == r"\\192.168.1.21\VR_E\VR\a.mp4"
    assert translate_stash_path("F:\\VR\\b.jpg", mapping) == r"\\192.168.1.21\VR_F\VR\b.jpg"


def test_translate_deep_prefix_from_autodiscovered_cache() -> None:
    mapping = {r"E:\VR": r"\\192.168.1.21\VR_E"}
    assert translate_stash_path("E:/VR/a.mp4", mapping) == r"\\192.168.1.21\VR_E\a.mp4"
    assert translate_stash_path(r"E:\VR\nested\b.mp4", mapping) == r"\\192.168.1.21\VR_E\nested\b.mp4"


def test_translate_uses_longest_matching_prefix() -> None:
    mapping = {
        "E:": r"\\stash\VR_E",
        r"E:\VR": r"\\stash\VR_E_ROOT",
        r"E:\VR\special": r"\\stash\VR_E_SPECIAL",
    }
    assert translate_stash_path(r"E:\VR\special\clip.mp4", mapping) == r"\\stash\VR_E_SPECIAL\clip.mp4"
    assert translate_stash_path(r"E:\VR\other\clip.mp4", mapping) == r"\\stash\VR_E_ROOT\other\clip.mp4"


def test_translate_requires_path_segment_boundary() -> None:
    mapping = {r"E:\VR": r"\\stash\VR_E"}
    assert translate_stash_path(r"E:\VR2\clip.mp4", mapping) == r"E:\VR2\clip.mp4"


def test_translate_preserves_unmapped_and_unc_paths() -> None:
    mapping = {r"E:\VR": r"\\stash\VR_E"}
    assert translate_stash_path(r"F:\VR\clip.mp4", mapping) == r"F:\VR\clip.mp4"
    assert translate_stash_path(r"\\stash\VR_E\clip.mp4", mapping) == r"\\stash\VR_E\clip.mp4"


def test_verify_inventory_binds_every_source_to_sha256_and_path_specific_key() -> None:
    inventory = _inventory()
    mapping = {"E:": r"\\stash\VR_E", "F:": r"\\stash\VR_F"}
    sizes = {
        r"\\stash\VR_E\VR\source.mp4": 100,
        r"\\stash\VR_F\VR\source.jpg": 50,
    }
    hashes = {
        r"\\stash\VR_E\VR\source.mp4": "a" * 64,
        r"\\stash\VR_F\VR\source.jpg": "b" * 64,
    }

    result = verify_inventory_sources(
        inventory,
        path_mapping=mapping,
        exists_file=lambda path: str(path) in sizes,
        file_size=lambda path: sizes[str(path)],
        hash_file=lambda path: hashes[str(path)],
    )

    assert result["source_count"] == 2
    assert result["video_count"] == 1
    assert result["image_count"] == 1
    assert result["total_bytes"] == 150
    assert result["all_sources_readable"] is True
    assert result["all_sources_sha256_bound"] is True
    assert result["source_keys_path_specific"] is True
    assert result["teacher_input_authority"] is True
    assert result["production_activation"] is False
    assert {item["sha256"] for item in result["sources"]} == {"a" * 64, "b" * 64}
    assert {item["source_key"] for item in result["sources"]} == {
        "scene:s1:E:/VR/source.mp4",
        "image:i1:F:/VR/source.jpg",
    }


def test_verify_inventory_accepts_autodiscovered_deep_prefix_mapping() -> None:
    inventory = _inventory()
    mapping = {r"E:\VR": r"\\stash\VR_E", r"F:\VR": r"\\stash\VR_F"}
    sizes = {
        r"\\stash\VR_E\source.mp4": 100,
        r"\\stash\VR_F\source.jpg": 50,
    }

    result = verify_inventory_sources(
        inventory,
        path_mapping=mapping,
        exists_file=lambda path: str(path) in sizes,
        file_size=lambda path: sizes[str(path)],
        hash_file=lambda path: ("a" if str(path).lower().endswith(".mp4") else "b") * 64,
    )

    assert {item["resolved_path"] for item in result["sources"]} == set(sizes)


def test_verify_inventory_distinguishes_multiple_files_in_same_scene() -> None:
    inventory = _inventory()
    inventory["videos"] = [
        {"scene_id": "s1", "path": "E:/VR/left.mp4", "size_bytes": 10},
        {"scene_id": "s1", "path": "E:/VR/right.mp4", "size_bytes": 20},
    ]
    inventory["video_file_count"] = 2
    mapping = {"E:": r"\\stash\VR_E", "F:": r"\\stash\VR_F"}
    sizes = {
        r"\\stash\VR_E\VR\left.mp4": 10,
        r"\\stash\VR_E\VR\right.mp4": 20,
        r"\\stash\VR_F\VR\source.jpg": 50,
    }

    result = verify_inventory_sources(
        inventory,
        path_mapping=mapping,
        exists_file=lambda path: str(path) in sizes,
        file_size=lambda path: sizes[str(path)],
        hash_file=lambda path: ("a" if str(path).endswith("left.mp4") else "b") * 64,
    )

    video_keys = {item["source_key"] for item in result["sources"] if item["kind"] == "video"}
    assert video_keys == {
        "scene:s1:E:/VR/left.mp4",
        "scene:s1:E:/VR/right.mp4",
    }


def test_verify_inventory_rejects_changed_size() -> None:
    with pytest.raises(PhotorealSourceVerifyError, match="size changed"):
        verify_inventory_sources(
            _inventory(),
            path_mapping={"E:": r"\\stash\VR_E", "F:": r"\\stash\VR_F"},
            exists_file=lambda _path: True,
            file_size=lambda path: 99 if str(path).lower().endswith("source.mp4") else 50,
            hash_file=lambda _path: "a" * 64,
        )


def test_verify_inventory_rejects_missing_source() -> None:
    with pytest.raises(PhotorealSourceVerifyError, match="not readable"):
        verify_inventory_sources(
            _inventory(),
            path_mapping={"E:": r"\\stash\VR_E", "F:": r"\\stash\VR_F"},
            exists_file=lambda path: not str(path).lower().endswith("source.jpg"),
            file_size=lambda _path: 100,
            hash_file=lambda _path: "a" * 64,
        )


def test_verify_inventory_rejects_runtime_authority_crossing() -> None:
    inventory = _inventory()
    inventory["runtime_dependency"] = True
    with pytest.raises(PhotorealSourceVerifyError, match="runtime/production"):
        verify_inventory_sources(
            inventory,
            path_mapping={},
            exists_file=lambda _path: True,
            file_size=lambda _path: 1,
            hash_file=lambda _path: "a" * 64,
        )
