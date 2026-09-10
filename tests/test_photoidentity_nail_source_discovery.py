from __future__ import annotations

from pathlib import Path

from PIL import Image

from bodyrig.photoidentity_nail_source_discovery import (
    MIN_HAND_NATIVE_CROP,
    MIN_FOOT_NATIVE_CROP,
    _claims_for_frame,
    select_nail_frame_candidates,
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
                "face_keypoints_2d": _points(70, base_x=700.0, base_y=200.0, spacing=6.0, confidence=0.9),
            }
        ]
    }


def _observation(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "scene_id": "scene-a",
        "source_ordinal": 1,
        "start_seconds": 2.0,
        "duration_seconds": 6.0,
        "target_confidence": 0.95,
        "target_screen_fraction": 0.8,
        "face_visibility": 0.8,
        "full_body_visibility": 0.9,
        "sharpness": 0.95,
        "occlusion": 0.02,
        "motion": 0.1,
        "view": "front",
    }
    value.update(overrides)
    return value


def test_large_source_frame_produces_review_candidates_but_not_nail_authority(tmp_path: Path) -> None:
    frame = tmp_path / "frame.png"
    Image.new("RGB", (1920, 1920), (127, 127, 127)).save(frame)
    claims = _claims_for_frame(
        _payload(),
        frame=frame,
        observation=_observation(),
        output_root=tmp_path / "crops",
    )
    assert set(claims) == {"left_fingernails", "right_fingernails", "left_toenails", "right_toenails"}
    assert claims["left_fingernails"]["native_crop_width"] >= MIN_HAND_NATIVE_CROP
    assert claims["left_toenails"]["native_crop_width"] >= MIN_FOOT_NATIVE_CROP
    assert all(item["width"] == 1024 and item["height"] == 1024 for item in claims.values())
    assert all("source_derived" not in item and "adapter" not in item for item in claims.values())


def test_upscaling_small_native_source_never_makes_candidate_review_eligible(tmp_path: Path) -> None:
    frame = tmp_path / "frame.png"
    Image.new("RGB", (320, 320), (127, 127, 127)).save(frame)
    payload = {
        "people": [
            {
                "pose_keypoints_2d": _points(25, base_x=80.0, base_y=180.0, spacing=5.0, confidence=0.9),
                "hand_left_keypoints_2d": _points(21, base_x=30.0, base_y=100.0, spacing=6.0, confidence=0.95),
                "hand_right_keypoints_2d": _points(21, base_x=180.0, base_y=100.0, spacing=6.0, confidence=0.95),
                "face_keypoints_2d": _points(70, base_x=100.0, base_y=30.0, spacing=1.0, confidence=0.9),
            }
        ]
    }
    claims = _claims_for_frame(
        payload,
        frame=frame,
        observation=_observation(),
        output_root=tmp_path / "crops",
    )
    assert claims
    assert all(item["width"] == 1024 for item in claims.values())
    assert not any(item["review_eligible"] is True for item in claims.values())


def test_missing_fingertips_cannot_become_fingernail_candidate(tmp_path: Path) -> None:
    frame = tmp_path / "frame.png"
    Image.new("RGB", (1920, 1920), (127, 127, 127)).save(frame)
    payload = _payload()
    left = payload["people"][0]["hand_left_keypoints_2d"]
    for index in (4, 8, 12, 16, 20):
        left[index * 3 + 2] = 0.0
    claims = _claims_for_frame(
        payload,
        frame=frame,
        observation=_observation(),
        output_root=tmp_path / "crops",
    )
    assert "left_fingernails" not in claims
    assert "right_fingernails" in claims


def test_blurry_or_occluded_source_stays_non_reviewable(tmp_path: Path) -> None:
    frame = tmp_path / "frame.png"
    Image.new("RGB", (1920, 1920), (127, 127, 127)).save(frame)
    for observation in (_observation(sharpness=0.4), _observation(occlusion=0.4)):
        claims = _claims_for_frame(
            _payload(),
            frame=frame,
            observation=observation,
            output_root=tmp_path / f"crops-{observation['sharpness']}-{observation['occlusion']}",
        )
        assert claims
        assert not any(item["review_eligible"] is True for item in claims.values())


def test_frame_selection_is_bounded_per_scene_and_prefers_source_quality() -> None:
    rows = []
    for scene_index in range(3):
        for index in range(20):
            rows.append(
                _observation(
                    scene_id=f"scene-{scene_index}",
                    source_ordinal=scene_index + 1,
                    start_seconds=float(index * 7),
                    sharpness=0.9 if index == 19 else 0.6,
                    target_screen_fraction=0.9 if index == 19 else 0.4,
                )
            )
    selected = select_nail_frame_candidates(rows)
    assert len(selected) <= 3 * 8
    assert any(row["start_seconds"] == 133.0 for row in selected)
