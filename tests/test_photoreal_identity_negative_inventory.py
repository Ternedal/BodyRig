from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_identity_negative_inventory import (
    PhotorealIdentityNegativeInventoryError,
    build_identity_negative_inventory,
    co_performer_counts,
)


def _scene(scene_id: str, performer_ids: list[str]) -> dict[str, object]:
    return {
        "id": scene_id,
        "performers": [{"id": performer_id, "name": f"P{performer_id}"} for performer_id in performer_ids],
    }


def _inventory(performer_id: str, *, include_safe: bool = True) -> dict[str, object]:
    videos = []
    images = []
    if include_safe:
        videos.append(
            {
                "scene_id": f"solo-{performer_id}",
                "path": f"E:/negative/{performer_id}-solo.mp4",
                "performer_count": 1,
                "information_score": 90.0,
                "projection": "flat",
                "stereo_layout": "mono",
                "width": 3840,
                "height": 2160,
                "duration_seconds": 120.0,
                "frame_rate": 30.0,
                "size_bytes": 1000,
            }
        )
        images.append(
            {
                "image_id": f"portrait-{performer_id}",
                "path": f"F:/negative/{performer_id}-portrait.jpg",
                "performer_count": 1,
                "source_binding": "direct-performer",
                "information_score": 120.0,
                "width": 6000,
                "height": 4000,
                "megapixels": 24.0,
                "size_bytes": 500,
            }
        )
    videos.append(
        {
            "scene_id": f"multi-{performer_id}",
            "path": f"E:/negative/{performer_id}-multi.mp4",
            "performer_count": 2,
            "information_score": 200.0,
            "projection": "flat",
            "stereo_layout": "mono",
            "width": 7680,
            "height": 4320,
            "duration_seconds": 120.0,
            "frame_rate": 60.0,
            "size_bytes": 2000,
        }
    )
    images.append(
        {
            "image_id": f"gallery-{performer_id}",
            "path": f"F:/negative/{performer_id}-gallery.jpg",
            "performer_count": 1,
            "source_binding": "performer-gallery",
            "information_score": 300.0,
            "width": 8000,
            "height": 6000,
            "megapixels": 48.0,
            "size_bytes": 900,
        }
    )
    return {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": performer_id,
        "performer_name": f"Performer {performer_id}",
        "videos": videos,
        "images": images,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _target_scenes() -> list[dict[str, object]]:
    return [
        _scene("s1", ["42", "7"]),
        _scene("s2", ["42", "7"]),
        _scene("s3", ["42", "8"]),
    ]


def test_co_performer_counts_are_target_bound() -> None:
    counts = co_performer_counts("42", _target_scenes())

    assert counts["7"] == 2
    assert counts["8"] == 1
    assert "42" not in counts


def test_negative_inventory_uses_only_other_single_performer_direct_sources() -> None:
    result = build_identity_negative_inventory(
        target_performer_id="42",
        target_scenes=_target_scenes(),
        negative_performer_inventories={"7": _inventory("7"), "8": _inventory("8")},
        max_negative_performers=2,
        sources_per_performer=3,
    )

    assert result["negative_performer_count"] == 2
    assert result["calibration_only"] is True
    assert result["photoreal_teacher_input"] is False
    assert result["identity_matching_authorized"] is False
    assert result["production_activation"] is False
    assert {item["subject_performer_id"] for item in result["sources"]} == {"7", "8"}
    assert all(item["target_performer_id"] == "42" for item in result["sources"])
    assert all(item["target_performer_absent"] is True for item in result["sources"])
    assert all(item["label_authority"] == "stash-single-performer-other-id-v1" for item in result["sources"])
    assert all("-multi.mp4" not in item["path"] for item in result["sources"])
    assert all("-gallery.jpg" not in item["path"] for item in result["sources"])


def test_negative_inventory_prefers_cross_media_diversity() -> None:
    result = build_identity_negative_inventory(
        target_performer_id="42",
        target_scenes=_target_scenes(),
        negative_performer_inventories={"7": _inventory("7")},
        max_negative_performers=1,
        sources_per_performer=2,
    )

    assert {item["kind"] for item in result["sources"]} == {"image", "video"}


def test_negative_inventory_never_accepts_target_as_negative_subject() -> None:
    with pytest.raises(PhotorealIdentityNegativeInventoryError, match="target performer cannot enter"):
        build_identity_negative_inventory(
            target_performer_id="42",
            target_scenes=_target_scenes(),
            negative_performer_inventories={"7": {**_inventory("7"), "performer_id": "42"}},
            max_negative_performers=1,
        )


def test_negative_inventory_rejects_target_scene_without_target_binding() -> None:
    scenes = copy.deepcopy(_target_scenes())
    scenes[0]["performers"] = [{"id": "7", "name": "P7"}]

    with pytest.raises(PhotorealIdentityNegativeInventoryError, match="lost target performer binding"):
        co_performer_counts("42", scenes)


def test_negative_inventory_fails_if_no_authoritative_negative_sources_exist() -> None:
    with pytest.raises(PhotorealIdentityNegativeInventoryError, match="no source-authoritative negative"):
        build_identity_negative_inventory(
            target_performer_id="42",
            target_scenes=_target_scenes(),
            negative_performer_inventories={"7": _inventory("7", include_safe=False)},
            max_negative_performers=1,
        )
