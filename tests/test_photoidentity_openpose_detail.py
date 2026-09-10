from __future__ import annotations

from bodyrig.photoidentity_openpose_detail import (
    ADAPTER,
    CAPABILITIES,
    REVISION,
    analyze_openpose_detail,
    merge_best_claims,
)


def _points(count: int, confidence: float, *, x0: float = 100.0, y0: float = 100.0, step: float = 8.0) -> list[float]:
    values: list[float] = []
    for index in range(count):
        values.extend([x0 + step * index, y0 + step * (index % 3), confidence])
    return values


def _payload() -> dict:
    body = _points(25, 0.95, x0=100.0, y0=200.0, step=15.0)
    # Give each BODY_25 foot cluster enough independent spatial extent.
    for point_index, (x, y) in {
        19: (400.0, 900.0),
        20: (475.0, 900.0),
        21: (410.0, 840.0),
        22: (900.0, 900.0),
        23: (975.0, 900.0),
        24: (910.0, 840.0),
    }.items():
        body[point_index * 3] = x
        body[point_index * 3 + 1] = y
    face = _points(70, 0.95, x0=400.0, y0=180.0, step=4.0)
    # Make the two eye contours span more than the 110px proof threshold.
    for offset, point_index in enumerate(range(36, 42)):
        face[point_index * 3] = 500.0 + offset * 12.0
        face[point_index * 3 + 1] = 260.0 + (offset % 2) * 6.0
    for offset, point_index in enumerate(range(42, 48)):
        face[point_index * 3] = 620.0 + offset * 12.0
        face[point_index * 3 + 1] = 260.0 + (offset % 2) * 6.0
    return {
        "people": [
            {
                "pose_keypoints_2d": body,
                "hand_left_keypoints_2d": _points(21, 0.95, x0=260.0, y0=520.0, step=10.0),
                "hand_right_keypoints_2d": _points(21, 0.95, x0=900.0, y0=520.0, step=10.0),
                "face_keypoints_2d": face,
            }
        ]
    }


def _observation(**changes) -> dict:
    value = {
        "target_confidence": 0.95,
        "face_visibility": 0.95,
        "full_body_visibility": 0.95,
        "sharpness": 0.95,
        "occlusion": 0.05,
        "view": "front",
    }
    value.update(changes)
    return value


def test_adapter_only_claims_domains_openpose_can_actually_prove() -> None:
    assert CAPABILITIES == ("eyes-detail", "hands-detail", "feet-detail")
    claims = analyze_openpose_detail(
        _payload(),
        scene_id="scene-1",
        observation=_observation(),
        frame_width=1920,
        frame_height=1080,
    )

    assert set(claims) == {"eyes_detail", "hands", "feet"}
    for values in claims.values():
        assert values[0]["source_derived"] is True
        assert values[0]["adapter"] == ADAPTER
        assert values[0]["revision"] == REVISION
        assert values[0]["quality"] >= 0.8

    # OpenPose must never be used as authority for these unsupported details.
    assert "hair_hairline" not in claims
    assert "skin_detail" not in claims
    assert "torso_chest" not in claims
    assert "fingernails_detail" not in claims
    assert "toenails_detail" not in claims


def test_eye_detail_requires_frontal_high_resolution_source() -> None:
    profile = analyze_openpose_detail(
        _payload(),
        scene_id="scene-1",
        observation=_observation(view="left_profile"),
        frame_width=1920,
        frame_height=1080,
    )
    assert "eyes_detail" not in profile

    tiny = _payload()
    face = tiny["people"][0]["face_keypoints_2d"]
    for offset, point_index in enumerate(range(36, 48)):
        face[point_index * 3] = 500.0 + offset * 3.0
        face[point_index * 3 + 1] = 260.0
    claims = analyze_openpose_detail(
        tiny,
        scene_id="scene-1",
        observation=_observation(),
        frame_width=1920,
        frame_height=1080,
    )
    assert claims["eyes_detail"][0]["quality"] < 0.8


def test_one_visible_hand_does_not_authorize_hands_detail() -> None:
    payload = _payload()
    payload["people"][0]["hand_right_keypoints_2d"] = _points(21, 0.0)
    claims = analyze_openpose_detail(
        payload,
        scene_id="scene-1",
        observation=_observation(),
        frame_width=1920,
        frame_height=1080,
    )
    assert "hands" not in claims


def test_feet_detail_is_not_toenail_authority() -> None:
    claims = analyze_openpose_detail(
        _payload(),
        scene_id="scene-1",
        observation=_observation(),
        frame_width=1920,
        frame_height=1080,
    )
    assert claims["feet"][0]["quality"] >= 0.8
    assert "toenails_detail" not in claims


def test_merge_keeps_best_claim_per_domain_and_scene() -> None:
    evidence = {
        "eyes_detail": [
            {"scene_id": "a", "quality": 0.81, "source_derived": True, "adapter": ADAPTER, "revision": REVISION}
        ]
    }
    merge_best_claims(
        evidence,
        {
            "eyes_detail": [
                {"scene_id": "a", "quality": 0.93, "source_derived": True, "adapter": ADAPTER, "revision": REVISION},
                {"scene_id": "b", "quality": 0.85, "source_derived": True, "adapter": ADAPTER, "revision": REVISION},
            ]
        },
    )
    assert [item["scene_id"] for item in evidence["eyes_detail"]] == ["a", "b"]
    assert evidence["eyes_detail"][0]["quality"] == 0.93
