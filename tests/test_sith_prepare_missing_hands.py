from __future__ import annotations

import json
from pathlib import Path

from bodyrig.sith_prepare import validate_openpose_result


def _points(count: int, confidence: float) -> list[float]:
    values: list[float] = []
    for index in range(count):
        values.extend((100.0 + index, 200.0 + index, confidence))
    return values


def test_validate_openpose_allows_missing_hand_detections(tmp_path: Path) -> None:
    path = tmp_path / "000_keypoints.json"
    path.write_text(
        json.dumps(
            {
                "version": 1.3,
                "people": [
                    {
                        "pose_keypoints_2d": _points(25, 0.9),
                        "hand_left_keypoints_2d": _points(21, 0.0),
                        "hand_right_keypoints_2d": _points(21, 0.0),
                        "face_keypoints_2d": _points(70, 0.9),
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    quality = validate_openpose_result(path)

    assert quality == {
        "body_confident": 25,
        "left_hand_confident": 0,
        "right_hand_confident": 0,
        "face_confident": 70,
    }
