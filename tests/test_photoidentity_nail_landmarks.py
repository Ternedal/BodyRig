from __future__ import annotations

import pytest

from bodyrig.photoidentity_nail_landmarks import (
    PhotoIdentityNailLandmarkError,
    _canvas_point,
    project_nail_landmarks,
)


def _points(count: int, *, base_x: float, base_y: float, spacing: float, confidence: float) -> list[float]:
    values: list[float] = []
    for index in range(count):
        values.extend([base_x + (index % 5) * spacing, base_y + (index // 5) * spacing, confidence])
    return values


def _payload(*, hand_conf: float = 0.95, foot_conf: float = 0.95) -> dict:
    body = _points(25, base_x=300.0, base_y=400.0, spacing=55.0, confidence=0.0)
    for index in (19, 20, 21, 22, 23, 24):
        body[index * 3] = 450.0 + (index - 19) * 65.0
        body[index * 3 + 1] = 1450.0 + ((index - 19) % 3) * 45.0
        body[index * 3 + 2] = foot_conf
    return {
        "people": [
            {
                "pose_keypoints_2d": body,
                "hand_left_keypoints_2d": _points(21, base_x=150.0, base_y=600.0, spacing=65.0, confidence=hand_conf),
                "hand_right_keypoints_2d": _points(21, base_x=1150.0, base_y=600.0, spacing=65.0, confidence=hand_conf),
            }
        ]
    }


def test_small_native_crop_projection_matches_centered_pil_thumbnail_semantics() -> None:
    projected = _canvas_point((100.0, 100.0, 0.9), crop=(100, 100, 300, 300))
    assert projected == {
        "x_norm": 0.40234375,
        "y_norm": 0.40234375,
        "confidence": 0.9,
    }
    opposite = _canvas_point((300.0, 300.0, 0.9), crop=(100, 100, 300, 300))
    assert opposite["x_norm"] == pytest.approx(0.59765625)
    assert opposite["y_norm"] == pytest.approx(0.59765625)


def test_hand_projection_preserves_five_semantic_fingertip_anchors_without_authority() -> None:
    result = project_nail_landmarks(
        _payload(),
        region="left_fingernails",
        frame_width=1920,
        frame_height=1920,
    )

    assert list(result["landmarks"]) == ["thumb", "index", "middle", "ring", "pinky"]
    assert result["required_landmark_count"] == 5
    assert result["observed_landmark_count"] == 5
    assert result["application_ready"] is True
    assert result["source_coordinate_authority"] == "openpose-semantic-landmarks"
    assert result["package_application_authority"] is False
    assert result["human_review_required"] is True
    assert result["production_activation"] is False
    for landmark in result["landmarks"].values():
        assert 0.0 <= landmark["x_norm"] <= 1.0
        assert 0.0 <= landmark["y_norm"] <= 1.0
        assert landmark["confidence"] >= 0.95


def test_four_of_five_fingertips_remain_non_application_ready() -> None:
    payload = _payload()
    hand = payload["people"][0]["hand_left_keypoints_2d"]
    hand[20 * 3 + 2] = 0.0

    result = project_nail_landmarks(
        payload,
        region="left_fingernails",
        frame_width=1920,
        frame_height=1920,
    )

    assert result["observed_landmark_count"] == 4
    assert result["application_ready"] is False
    assert "pinky" not in result["landmarks"]
    assert result["package_application_authority"] is False


def test_foot_projection_binds_big_toe_small_toe_and_heel_only() -> None:
    result = project_nail_landmarks(
        _payload(),
        region="right_toenails",
        frame_width=1920,
        frame_height=1920,
    )

    assert list(result["landmarks"]) == ["big_toe", "small_toe", "heel"]
    assert result["required_landmark_count"] == 3
    assert result["observed_landmark_count"] == 3
    assert result["application_ready"] is True
    assert result["package_application_authority"] is False
    assert result["production_activation"] is False


def test_invalid_scope_and_incomplete_openpose_fail_closed() -> None:
    with pytest.raises(PhotoIdentityNailLandmarkError, match="region is not canonical"):
        project_nail_landmarks(_payload(), region="left_hand", frame_width=1920, frame_height=1920)
    with pytest.raises(PhotoIdentityNailLandmarkError, match="dimensions are invalid"):
        project_nail_landmarks(_payload(), region="left_fingernails", frame_width=True, frame_height=1920)

    payload = _payload()
    body = payload["people"][0]["pose_keypoints_2d"]
    body[22 * 3 + 2] = 0.0
    with pytest.raises(PhotoIdentityNailLandmarkError, match="right foot lacks"):
        project_nail_landmarks(payload, region="right_toenails", frame_width=1920, frame_height=1920)
