from __future__ import annotations

import pytest

from bodyrig.photoreal_dataset_plan import PhotorealDatasetPlanError, build_dataset_plan


def _inventory() -> dict[str, object]:
    return {
        "format": "bodyrig-photoreal-source-inventory",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "performer": {"id": "42", "name": "Performer 42", "disambiguation": ""},
        "videos": [
            {
                "scene_id": "s1",
                "path": "E:/stash/a.mp4",
                "information_score": 120.0,
                "projection": "vr180",
                "stereo_layout": "side-by-side",
                "width": 7680,
                "height": 3840,
                "duration_seconds": 3600.0,
                "frame_rate": 60.0,
                "performer_count": 1,
            },
            {
                "scene_id": "s1",
                "path": "E:/stash/a-alt.mkv",
                "information_score": 80.0,
                "projection": "vr180",
                "stereo_layout": "side-by-side",
                "width": 7680,
                "height": 3840,
                "duration_seconds": 3600.0,
                "frame_rate": 60.0,
                "performer_count": 1,
            },
            {
                "scene_id": "s2",
                "path": "E:/stash/b.mp4",
                "information_score": 90.0,
                "projection": "flat",
                "stereo_layout": "mono",
                "width": 3840,
                "height": 2160,
                "duration_seconds": 1800.0,
                "frame_rate": 30.0,
                "performer_count": 2,
            },
        ],
        "images": [
            {
                "image_id": "i1",
                "path": "F:/stash/1.jpg",
                "information_score": 200.0,
                "source_binding": "direct-performer",
                "performer_count": 1,
                "gallery_ids": ["g1"],
                "width": 6000,
                "height": 4000,
                "megapixels": 24.0,
            },
            {
                "image_id": "i2",
                "path": "F:/stash/2.jpg",
                "information_score": 180.0,
                "source_binding": "performer-gallery",
                "performer_count": 0,
                "gallery_ids": ["g1"],
                "width": 5000,
                "height": 3333,
                "megapixels": 16.665,
            },
            {
                "image_id": "i3",
                "path": "F:/stash/3.jpg",
                "information_score": 160.0,
                "source_binding": "direct-performer",
                "performer_count": 1,
                "gallery_ids": [],
                "width": 4500,
                "height": 3000,
                "megapixels": 13.5,
            },
        ],
        "build_only": True,
        "photoreal_teacher_input": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_plan_is_source_group_disjoint_and_deterministic() -> None:
    first = build_dataset_plan(_inventory(), eval_fraction=0.25, seed="fixed")
    second = build_dataset_plan(_inventory(), eval_fraction=0.25, seed="fixed")

    assert first == second
    train_groups = {item["group_id"] for item in first["train"]}
    eval_groups = {item["group_id"] for item in first["evaluation"]}
    assert train_groups.isdisjoint(eval_groups)
    assert first["performer_id"] == "42"
    assert first["performer_name"] == "Performer 42"
    assert first["leakage_policy"] == "source-group-disjoint-v1"
    assert first["identity_bootstrap_policy"] == "train-only-single-performer-direct-binding-v1"
    assert first["teacher_training_authorized"] is False
    assert first["view_analysis_required"] is True
    assert first["production_activation"] is False
    video_records = [item for split in ("train", "evaluation") for item in first[split] if item["kind"] == "video"]
    assert {item["stereo_layout"] for item in video_records} == {"side-by-side", "mono"}
    assert {item["performer_count"] for item in video_records} == {1, 2}
    assert all(item["source_binding"] == "scene-performer" for item in video_records)


def test_all_files_from_same_scene_stay_together() -> None:
    result = build_dataset_plan(_inventory(), eval_fraction=0.25, seed="scene-test")
    assignment = {}
    for split_name in ("train", "evaluation"):
        for item in result[split_name]:
            if item["group_id"] == "scene:s1":
                assignment.setdefault(split_name, []).append(item)

    assert len(assignment) == 1
    assert len(next(iter(assignment.values()))) == 2


def test_gallery_images_stay_together() -> None:
    result = build_dataset_plan(_inventory(), eval_fraction=0.25, seed="gallery-test")
    splits = {
        split_name
        for split_name in ("train", "evaluation")
        if any(item["group_id"] == "gallery:g1" for item in result[split_name])
    }
    assert len(splits) == 1
    selected = result[next(iter(splits))]
    assert sum(1 for item in selected if item["group_id"] == "gallery:g1") == 2


def test_plan_preserves_identity_authority_metadata() -> None:
    result = build_dataset_plan(_inventory(), eval_fraction=0.25, seed="identity-metadata")
    records = [item for split in ("train", "evaluation") for item in result[split]]
    direct = next(item for item in records if item["source_id"].startswith("image:i3:"))
    multi = next(item for item in records if item["source_id"].startswith("scene:s2:"))

    assert direct["source_binding"] == "direct-performer"
    assert direct["performer_count"] == 1
    assert multi["source_binding"] == "scene-performer"
    assert multi["performer_count"] == 2


def test_plan_refuses_single_source_group() -> None:
    inventory = _inventory()
    inventory["videos"] = inventory["videos"][:2]
    inventory["images"] = []

    with pytest.raises(PhotorealDatasetPlanError, match="at least two independent source groups"):
        build_dataset_plan(inventory)


def test_plan_refuses_authority_boundary_violation() -> None:
    inventory = _inventory()
    inventory["production_activation"] = True

    with pytest.raises(PhotorealDatasetPlanError, match="authority boundary"):
        build_dataset_plan(inventory)


def test_plan_refuses_inconsistent_performer_identity() -> None:
    inventory = _inventory()
    inventory["performer"]["id"] = "99"

    with pytest.raises(PhotorealDatasetPlanError, match="performer identity is inconsistent"):
        build_dataset_plan(inventory)


def test_plan_refuses_boolean_performer_count() -> None:
    inventory = _inventory()
    inventory["videos"][0]["performer_count"] = True

    with pytest.raises(PhotorealDatasetPlanError, match="cannot be boolean"):
        build_dataset_plan(inventory)
