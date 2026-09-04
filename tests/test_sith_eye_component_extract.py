from __future__ import annotations

import sys
from pathlib import Path

import pytest


BRIDGES = Path(__file__).resolve().parents[1] / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_eye_component_extract import (  # noqa: E402
    EyeComponentExtractError,
    LEFT_EYE_JOINT,
    RIGHT_EYE_JOINT,
    select_eye_faces,
)


def _weights() -> list[list[float]]:
    rows: list[list[float]] = []
    for index in range(12):
        row = [0.0] * 55
        row[0] = 1.0
        if index < 6:
            row[0] = 0.1
            row[LEFT_EYE_JOINT] = 0.9
        else:
            row[0] = 0.1
            row[RIGHT_EYE_JOINT] = 0.9
        rows.append(row)
    return rows


def test_eye_selector_isolates_left_and_right_lbs_faces() -> None:
    faces = [
        [0, 1, 2],
        [2, 3, 4],
        [4, 5, 0],
        [6, 7, 8],
        [8, 9, 10],
        [10, 11, 6],
        [0, 6, 1],
    ]

    left = select_eye_faces(lbs_weights=_weights(), faces=faces, joint_index=LEFT_EYE_JOINT)
    right = select_eye_faces(lbs_weights=_weights(), faces=faces, joint_index=RIGHT_EYE_JOINT)

    assert left == [0, 1, 2]
    assert right == [3, 4, 5]
    assert not set(left) & set(right)


def test_eye_selector_rejects_invalid_weight_topology() -> None:
    weights = _weights()
    weights[0] = [1.0]

    with pytest.raises(EyeComponentExtractError, match="eye joint is outside"):
        select_eye_faces(
            lbs_weights=weights,
            faces=[[0, 1, 2]],
            joint_index=LEFT_EYE_JOINT,
        )


def test_eye_selector_does_not_claim_mixed_face_as_eye_geometry() -> None:
    faces = [[0, 1, 6]]

    assert select_eye_faces(lbs_weights=_weights(), faces=faces, joint_index=LEFT_EYE_JOINT) == []
    assert select_eye_faces(lbs_weights=_weights(), faces=faces, joint_index=RIGHT_EYE_JOINT) == []
