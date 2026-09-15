from __future__ import annotations

import pytest

from bodyrig.photoreal_identity_negative_inventory import (
    PhotorealIdentityNegativeInventoryError,
    build_identity_negative_inventory,
)


def _scene(scene_id: str, target: str, other: str) -> dict[str, object]:
    return {
        "id": scene_id,
        "performers": [
            {"id": target, "name": f"P{target}"},
            {"id": other, "name": f"P{other}"},
        ],
    }


def _inventory(performer_id: str, *, include_flat: bool = True) -> dict[str, object]:
    videos: list[dict[str, object]] = [
        {
            "scene_id": f"spatial-{performer_id}",
            "path": f"E:/negative/{performer_id}-spatial.mp4",
            "performer_count": 1,
            "information_score": 999.0,
            "projection": "vr180",
            "stereo_layout": "side-by-side",
            "width": 7680,
            "height": 3840,
            "duration_seconds": 120.0,
            "frame_rate": 60.0,
            "size_bytes": 2000,
        }
    ]
    if include_flat:
        videos.append(
            {
                "scene_id": f"flat-{performer_id}",
                "path": f"E:/negative/{performer_id}-flat.mp4",
                "performer_count": 1,
                "information_score": 10.0,
                "projection": "flat",
                "stereo_layout": "mono",
                "width": 3840,
                "height": 2160,
                "duration_seconds": 120.0,
                "frame_rate": 30.0,
                "size_bytes": 1000,
            }
        )
    return {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": performer_id,
        "performer_name": f"Performer {performer_id}",
        "videos": videos,
        "images": [],
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_negative_inventory_excludes_spatial_sources_before_calibration() -> None:
    result = build_identity_negative_inventory(
        target_performer_id="42",
        target_scenes=[_scene("s1", "42", "7"), _scene("s2", "42", "8")],
        negative_performer_inventories={"7": _inventory("7"), "8": _inventory("8")},
        max_negative_performers=2,
        sources_per_performer=2,
    )

    videos = [item for item in result["sources"] if item["kind"] == "video"]
    assert len(videos) == 2
    assert all(item["projection"] == "flat" for item in videos)
    assert all("-spatial.mp4" not in item["path"] for item in videos)


def test_negative_inventory_fails_cleanly_when_only_spatial_negatives_exist() -> None:
    with pytest.raises(PhotorealIdentityNegativeInventoryError, match="no source-authoritative negative"):
        build_identity_negative_inventory(
            target_performer_id="42",
            target_scenes=[_scene("s1", "42", "7")],
            negative_performer_inventories={"7": _inventory("7", include_flat=False)},
            max_negative_performers=1,
            sources_per_performer=2,
        )
