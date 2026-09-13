from __future__ import annotations

import pytest

from bodyrig.photoidentity_nail_landmarks import (
    PhotoIdentityNailLandmarkError,
    normalized_crop_to_pixels,
    project_nail_landmarks_to_crop,
)


def _points(count: int, *, base_x: float, base_y: float, spacing: float, confidence: float) -> list[float]:
    values: list[float] = []
    for index in range(count):
        values.extend([base_x + (index % 5) * spacing, base_y + (index // 5) * spacing, confidence])
    return values


def _payload() -> dict:
    body = _points(25, base_x=100.0, base_y=100.0, spacing=10.0, confidence=0.0)
    for index, point in {
        19: (300.0, 420.0),
        20: (360.0, 420.0),
        21: (330.0, 470.0),
        22: (700.0, 420.0),
        23: (760.0, 420.0),
        24: (730.0, 470.0),
    }.items():
        body[index * 3] = point[0]
        body[index * 3 + 1] = point[1]
        body[index * 3 + 2] = 0.95
    return {
        "people": [
            {
                "pose_keypoints_2d": body,
                "hand_left_keypoints_2d": _points(21, base_x=200.0, base_y=200.0, spacing=20.0, confidence=0.95),
                "hand_right_keypoints_2d": _points(21, base_x=600.0, base_y=200.0, spacing=20.0, confidence=0.95),
            }
        ]
    }


def test_normalized_operator_crop_maps_to_deterministic_source_pixels() -> None:
    crop = normalized_crop_to_pixels(
        [0.25, 0.20, 0.50, 0.40],
        frame_width=1000,
        frame_height=500,
    )
    assert crop == (250, 100, 750, 300)


def test_non_square_operator_crop_uses_ffmpeg_scale_pad_semantics() -> None:
    payload = _payload()
    # 400x200 source crop -> 1024x512 render centered vertically in a 1024 square.
    result = project_nail_landmarks_to_crop(
        payload,
        region="left_fingernails",
        frame_width=1000,
        frame_height=500,
        crop_px=(150, 150, 550, 350),
        upscale_to_canvas=True,
    )

    thumb = result["landmarks"]["thumb"]
    # Tip 4 is (280,200). Relative to the crop: (130,50).
    # scale=1024/400=2.56, output height=512, y pad=256.
    assert thumb["x_norm"] == pytest.approx((130.0 * 2.56) / 1024.0, abs=1e-8)
    assert thumb["y_norm"] == pytest.approx((256.0 + 50.0 * 2.56) / 1024.0, abs=1e-8)
    assert result["source_coordinate_authority"] == "openpose-semantic-landmarks-explicit-crop"
    assert result["package_application_authority"] is False
    assert result["human_review_required"] is True
    assert result["production_activation"] is False


def test_operator_crop_that_excludes_tips_is_not_application_ready() -> None:
    payload = _payload()
    result = project_nail_landmarks_to_crop(
        payload,
        region="left_fingernails",
        frame_width=1000,
        frame_height=500,
        crop_px=(150, 150, 250, 350),
    )
    assert result["observed_landmark_count"] < result["required_landmark_count"]
    assert result["application_ready"] is False
    assert result["package_application_authority"] is False


def test_foot_crop_requires_semantic_anchors_inside_selected_crop_for_readiness() -> None:
    payload = _payload()
    ready = project_nail_landmarks_to_crop(
        payload,
        region="left_toenails",
        frame_width=1000,
        frame_height=500,
        crop_px=(250, 390, 420, 500),
    )
    assert list(ready["landmarks"]) == ["big_toe", "small_toe", "heel"]
    assert ready["application_ready"] is True

    partial = project_nail_landmarks_to_crop(
        payload,
        region="left_toenails",
        frame_width=1000,
        frame_height=500,
        crop_px=(250, 390, 345, 500),
    )
    assert partial["application_ready"] is False


def test_invalid_normalized_or_pixel_crop_fails_closed() -> None:
    with pytest.raises(PhotoIdentityNailLandmarkError, match="escaped source frame bounds"):
        normalized_crop_to_pixels([0.9, 0.1, 0.2, 0.4], frame_width=1000, frame_height=500)
    with pytest.raises(PhotoIdentityNailLandmarkError, match="escaped source frame bounds"):
        project_nail_landmarks_to_crop(
            _payload(),
            region="left_fingernails",
            frame_width=1000,
            frame_height=500,
            crop_px=(0, 0, 1001, 500),
        )
