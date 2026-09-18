from __future__ import annotations

from bodyrig.photoreal_inventory_path_map import build_inventory_path_map


def test_exhaustive_path_map_inference_stays_linear_in_large_source_set() -> None:
    count = 1000
    inventory = {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": "42",
        "video_file_count": count,
        "image_file_count": 0,
        "summary": {"source_universe_exhaustive": True},
        "videos": [
            {"scene_id": str(index), "path": rf"E:\VR\scene-{index:04d}\clip.mp4"}
            for index in range(count)
        ],
        "images": [],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }
    expected_files = {
        rf"\\stashbox\VR_E\scene-{index:04d}\clip.mp4"
        for index in range(count)
    }
    file_checks = 0

    def is_file(value: str) -> bool:
        nonlocal file_checks
        file_checks += 1
        return value in expected_files

    result = build_inventory_path_map(
        inventory,
        stash_url="http://stashbox:9999",
        is_dir=lambda value: value == r"\\stashbox\VR_E",
        is_file=is_file,
    )

    assert result["mapping"] == {r"E:\VR": r"\\stashbox\VR_E"}
    assert result["proof"][0]["verified_files"] == count
    # One common-prefix proof pass + one final exact-coverage pass, with small constant overhead.
    assert file_checks <= count * 2 + 10
