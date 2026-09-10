from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from bodyrig.photoidentity_anatomy_source_discovery import (
    PhotoIdentityAnatomyDiscoveryError,
    _regions_for_frame,
    _source_quality,
    select_anatomy_frame_candidates,
)


def _body25(scale: float = 1.0) -> list[float]:
    points = [
        (960, 140),  # nose
        (960, 220),  # neck
        (760, 260),  # right shoulder
        (680, 420),
        (650, 560),
        (1160, 260),  # left shoulder
        (1240, 420),
        (1270, 560),
        (960, 580),  # mid hip
        (820, 580),
        (840, 760),
        (850, 960),
        (1100, 580),
        (1080, 760),
        (1070, 960),
        (930, 120),
        (990, 120),
        (900, 130),
        (1020, 130),
        (1080, 1010),
        (1100, 1000),
        (1060, 980),
        (840, 1010),
        (820, 1000),
        (860, 980),
    ]
    values: list[float] = []
    for x, y in points:
        values.extend([x * scale, y * scale, 0.95])
    return values


def _observation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "target_confidence": 0.95,
        "target_screen_fraction": 0.55,
        "face_visibility": 0.05,
        "full_body_visibility": 0.95,
        "sharpness": 0.95,
        "occlusion": 0.05,
        "view": "unknown",
    }
    value.update(overrides)
    return value


def test_high_quality_body_frame_produces_review_candidates_without_machine_authority(tmp_path: Path) -> None:
    frame = tmp_path / "source.png"
    Image.new("RGB", (1920, 1080), (80, 80, 80)).save(frame)
    payload = {"people": [{"pose_keypoints_2d": _body25()}]}
    regions = _regions_for_frame(
        payload,
        frame=frame,
        observation=_observation(),
        output_root=tmp_path / "out",
    )
    assert set(regions) == {"rear_body", "torso_chest", "waist_hips"}
    for entry in regions.values():
        assert entry["review_eligible"] is True
        assert entry["source_quality"] >= 0.80
        assert entry["machine_asserts_anatomy_visible"] is False
        assert entry["machine_asserts_rear_orientation"] is False
        assert entry["width"] == 1024
        assert entry["height"] == 1024


def test_small_native_source_cannot_gain_detail_authority_from_1024_canvas(tmp_path: Path) -> None:
    frame = tmp_path / "small.png"
    Image.new("RGB", (480, 270), (80, 80, 80)).save(frame)
    payload = {"people": [{"pose_keypoints_2d": _body25(scale=0.25)}]}
    regions = _regions_for_frame(
        payload,
        frame=frame,
        observation=_observation(),
        output_root=tmp_path / "out",
    )
    assert regions
    assert any(entry["review_eligible"] is False for entry in regions.values())
    assert all(entry["width"] == 1024 and entry["height"] == 1024 for entry in regions.values())
    assert any(
        entry["native_crop_width"] < 300 or entry["native_crop_height"] < 260
        for entry in regions.values()
    )


def test_multiple_people_never_produce_anatomy_candidates(tmp_path: Path) -> None:
    frame = tmp_path / "source.png"
    Image.new("RGB", (1920, 1080), (80, 80, 80)).save(frame)
    person = {"pose_keypoints_2d": _body25()}
    assert _regions_for_frame(
        {"people": [person, person]},
        frame=frame,
        observation=_observation(),
        output_root=tmp_path / "out",
    ) == {}


def test_unknown_low_face_view_is_only_a_ranking_hint_not_rear_authority(tmp_path: Path) -> None:
    frame = tmp_path / "source.png"
    Image.new("RGB", (1920, 1080), (80, 80, 80)).save(frame)
    regions = _regions_for_frame(
        {"people": [{"pose_keypoints_2d": _body25()}]},
        frame=frame,
        observation=_observation(view="unknown", face_visibility=0.0),
        output_root=tmp_path / "out",
    )
    assert regions["rear_body"]["review_eligible"] is True
    assert regions["rear_body"]["machine_asserts_rear_orientation"] is False


def test_source_quality_is_weakest_leg_and_rejects_non_finite_values() -> None:
    quality = _source_quality(
        point_confidence=0.94,
        native_width=800,
        native_height=800,
        required_width=300,
        required_height=300,
        observation=_observation(sharpness=0.83, occlusion=0.05),
        require_full_body=False,
    )
    assert quality == 0.83
    with pytest.raises(PhotoIdentityAnatomyDiscoveryError, match="must be in 0..1"):
        _source_quality(
            point_confidence=0.94,
            native_width=800,
            native_height=800,
            required_width=300,
            required_height=300,
            observation=_observation(sharpness=float("nan")),
            require_full_body=False,
        )


def test_candidate_selection_deduplicates_same_scene_source_midpoint() -> None:
    rows = [
        {
            "scene_id": "scene-a",
            "source_ordinal": 1,
            "start_seconds": 0.0,
            "duration_seconds": 6.0,
            "target_confidence": 0.9,
            "target_screen_fraction": 0.5,
            "face_visibility": 0.1,
            "sharpness": 0.9,
            "occlusion": 0.05,
            "view": "unknown",
        },
        {
            "scene_id": "scene-a",
            "source_ordinal": 1,
            "start_seconds": 0.0,
            "duration_seconds": 6.0,
            "target_confidence": 0.8,
            "target_screen_fraction": 0.4,
            "face_visibility": 0.1,
            "sharpness": 0.8,
            "occlusion": 0.05,
            "view": "unknown",
        },
    ]
    selected = select_anatomy_frame_candidates(rows)
    assert len(selected) == 1
