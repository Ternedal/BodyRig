from __future__ import annotations

import copy

import pytest

from bodyrig.photoreal_scan_plan import PhotorealScanPlanError, build_scan_plan


def _video(
    source_key: str,
    group_id: str,
    *,
    projection: str,
    stereo_layout: str,
    duration: float,
    split: str,
) -> tuple[str, dict[str, object]]:
    return split, {
        "kind": "video",
        "source_id": source_key,
        "group_id": group_id,
        "path": source_key.split(":", 2)[-1],
        "information_score": 100.0,
        "projection": projection,
        "stereo_layout": stereo_layout,
        "width": 7680 if stereo_layout != "mono" else 3840,
        "height": 3840 if stereo_layout != "mono" else 2160,
        "duration_seconds": duration,
        "frame_rate": 60.0,
    }


def _image(source_key: str, group_id: str, *, split: str) -> tuple[str, dict[str, object]]:
    return split, {
        "kind": "image",
        "source_id": source_key,
        "group_id": group_id,
        "path": source_key.split(":", 2)[-1],
        "information_score": 100.0,
        "source_binding": "direct-performer",
        "width": 6000,
        "height": 4000,
        "megapixels": 24.0,
    }


def _plan() -> dict[str, object]:
    records = [
        _video(
            "scene:s-flat:E:/flat.mp4",
            "scene:s-flat",
            projection="flat",
            stereo_layout="mono",
            duration=50.0,
            split="train",
        ),
        _video(
            "scene:s-vr:E:/vr180-sbs.mp4",
            "scene:s-vr",
            projection="vr180",
            stereo_layout="side-by-side",
            duration=3600.0,
            split="evaluation",
        ),
        _image("image:i1:F:/portrait.jpg", "image:i1", split="evaluation"),
    ]
    train = [item for split, item in records if split == "train"]
    evaluation = [item for split, item in records if split == "evaluation"]
    return {
        "format": "bodyrig-photoreal-dataset-plan",
        "version": 1,
        "performer_id": "42",
        "performer_name": "Performer 42",
        "train": train,
        "evaluation": evaluation,
        "teacher_training_authorized": False,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def _receipt(plan: dict[str, object]) -> dict[str, object]:
    sources = []
    for split_name in ("train", "evaluation"):
        for index, item in enumerate(plan[split_name]):
            key = str(item["source_id"])
            sources.append(
                {
                    "kind": item["kind"],
                    "source_id": key.split(":", 2)[1],
                    "source_key": key,
                    "resolved_path": rf"\\stash\verified\{split_name}-{index}.bin",
                    "sha256": format(index + (1 if split_name == "train" else 8), "x") * 64,
                }
            )
    return {
        "format": "bodyrig-photoreal-source-receipt",
        "version": 1,
        "performer_id": "42",
        "sources": sources,
        "all_sources_readable": True,
        "all_sources_sha256_bound": True,
        "source_keys_path_specific": True,
        "build_only": True,
        "runtime_dependency": False,
        "production_activation": False,
    }


def test_scan_plan_is_deterministic_and_covers_every_source() -> None:
    plan = _plan()
    receipt = _receipt(plan)

    first = build_scan_plan(plan, receipt)
    second = build_scan_plan(plan, receipt)

    assert first == second
    assert first["source_count"] == 3
    assert first["all_sources_sha256_bound"] is True
    assert first["train_evaluation_assignment_inherited"] is True
    assert first["teacher_training_authorized"] is False
    assert first["production_activation"] is False
    assert {item["source_key"] for item in first["sources"]} == {
        "scene:s-flat:E:/flat.mp4",
        "scene:s-vr:E:/vr180-sbs.mp4",
        "image:i1:F:/portrait.jpg",
    }


def test_scan_plan_splits_stereo_eyes_and_caps_long_video_sampling() -> None:
    result = build_scan_plan(_plan(), _receipt(_plan()))
    vr = next(item for item in result["sources"] if item["source_key"].startswith("scene:s-vr:"))

    assert vr["projection"] == "vr180"
    assert vr["stereo_layout"] == "side-by-side"
    assert vr["decode_mode"] == "spatial-deprojection-required"
    assert vr["sample_count"] == 240  # 120 timestamps x two eyes
    assert {item["eye"] for item in vr["samples"]} == {"left", "right"}
    timestamps = sorted({item["timestamp_seconds"] for item in vr["samples"]})
    assert len(timestamps) == 120
    assert timestamps[0] > 0.0
    assert timestamps[-1] < 3600.0


def test_scan_plan_uses_minimum_midpoint_samples_for_short_mono_video() -> None:
    result = build_scan_plan(_plan(), _receipt(_plan()))
    flat = next(item for item in result["sources"] if item["source_key"].startswith("scene:s-flat:"))

    assert flat["decode_mode"] == "rectilinear-mono"
    assert flat["sample_count"] == 12
    assert {item["eye"] for item in flat["samples"]} == {"mono"}
    assert flat["samples"][0]["timestamp_seconds"] > 0.0
    assert flat["samples"][-1]["timestamp_seconds"] < 50.0


def test_scan_plan_treats_still_image_as_one_direct_sample() -> None:
    result = build_scan_plan(_plan(), _receipt(_plan()))
    image = next(item for item in result["sources"] if item["kind"] == "image")

    assert image["decode_mode"] == "image-direct"
    assert image["projection"] == "flat"
    assert image["stereo_layout"] == "mono"
    assert image["samples"] == [{"timestamp_seconds": None, "eye": "mono"}]


def test_scan_plan_refuses_projection_ambiguity_instead_of_guessing() -> None:
    plan = _plan()
    plan = copy.deepcopy(plan)
    plan["train"][0]["projection"] = "projection-ambiguous-2to1"

    with pytest.raises(PhotorealScanPlanError, match="cannot enter frame analysis"):
        build_scan_plan(plan, _receipt(plan))


def test_scan_plan_refuses_unknown_stereo_layout() -> None:
    plan = _plan()
    plan = copy.deepcopy(plan)
    plan["evaluation"][0]["stereo_layout"] = "stereo-unknown"

    with pytest.raises(PhotorealScanPlanError, match="cannot enter frame analysis"):
        build_scan_plan(plan, _receipt(plan))


def test_scan_plan_rejects_plan_receipt_universe_mismatch() -> None:
    plan = _plan()
    receipt = _receipt(plan)
    receipt["sources"].pop()

    with pytest.raises(PhotorealScanPlanError, match="source universe mismatch"):
        build_scan_plan(plan, receipt)
