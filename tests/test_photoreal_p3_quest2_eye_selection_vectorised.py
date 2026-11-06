"""The vectorised eye-triangle selection must be indistinguishable from the
per-face reference loop: same selected faces, same error, same error
precedence (first offending face; index range before weight validity),
and irregular skinning universes still go through the loop."""
from __future__ import annotations

import math
import random

import pytest

from bodyrig.photoreal_p3_quest2_eye_component import (
    FACE_EYE_WEIGHT_THRESHOLD,
    VERTEX_EYE_WEIGHT_THRESHOLD,
    PhotorealP3Quest2EyeComponentError,
    _select_eye_triangles_reference,
    _select_eye_triangles_vectorised,
    select_eye_triangles,
)

JOINT = 23


def _universe(seed: int, vertices: int = 400, faces: int = 600):
    rng = random.Random(seed)
    joints = []
    weights = []
    for _ in range(vertices):
        js = [rng.choice([JOINT, JOINT, 24, 0, 5]) for _ in range(4)]
        raw = [rng.random() for _ in range(4)]
        # Some vertices sit exactly on the thresholds, where ordering of the
        # float sum would show up first.
        if rng.random() < 0.15:
            raw = [VERTEX_EYE_WEIGHT_THRESHOLD, 0.0, 0.0, 0.0]
            js = [JOINT, 0, 0, 0]
        if rng.random() < 0.15:
            raw = [FACE_EYE_WEIGHT_THRESHOLD / 2.0, FACE_EYE_WEIGHT_THRESHOLD / 2.0, 0.0, 0.0]
            js = [JOINT, JOINT, 0, 0]
        joints.append(tuple(js))
        weights.append(tuple(raw))
    indices = [rng.randrange(vertices) for _ in range(faces * 3)]
    return indices, joints, weights


def _both(**kwargs):
    fast = _select_eye_triangles_vectorised(**kwargs)
    assert fast is not None, "regular universe must take the vectorised path"
    return fast, _select_eye_triangles_reference(**kwargs)


@pytest.mark.parametrize("seed", range(12))
def test_vectorised_selection_matches_reference(seed: int) -> None:
    indices, joints, weights = _universe(seed)
    fast, slow = _both(indices=indices, joints=joints, weights=weights, joint_index=JOINT)
    assert fast == slow
    assert slow, "fixture should select something"


def test_public_entry_point_uses_vectorised_result() -> None:
    indices, joints, weights = _universe(99)
    expected = _select_eye_triangles_reference(
        indices=indices, joints=joints, weights=weights, joint_index=JOINT
    )
    assert select_eye_triangles(
        indices=indices, joints=joints, weights=weights, joint_index=JOINT, minimum_faces=1
    ) == expected


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda i, j, w: (i[:9] + [len(j)] + i[10:], j, w), "escapes vertex universe"),
        (lambda i, j, w: (i[:9] + [-1] + i[10:], j, w), "escapes vertex universe"),
        (lambda i, j, w: (i, j, w[: i[4]] + [(math.nan, 0.0, 0.0, 0.0)] + w[i[4] + 1 :]), "weight is invalid"),
        (lambda i, j, w: (i, j, w[: i[4]] + [(-0.1, 0.0, 0.0, 0.0)] + w[i[4] + 1 :]), "weight is invalid"),
        (lambda i, j, w: (i, j, w[: i[4]] + [(math.inf, 0.0, 0.0, 0.0)] + w[i[4] + 1 :]), "weight is invalid"),
    ],
)
def test_vectorised_errors_match_reference(mutate, message) -> None:
    indices, joints, weights = _universe(3)
    indices, joints, weights = mutate(list(indices), list(joints), list(weights))
    with pytest.raises(PhotorealP3Quest2EyeComponentError, match=message):
        _select_eye_triangles_reference(indices=indices, joints=joints, weights=weights, joint_index=JOINT)
    with pytest.raises(PhotorealP3Quest2EyeComponentError, match=message):
        _select_eye_triangles_vectorised(indices=indices, joints=joints, weights=weights, joint_index=JOINT)


def test_error_precedence_is_first_face_then_index_before_weight() -> None:
    # Face 1 (vertices 3,4,5) carries an invalid weight; face 4 escapes the
    # universe. The loop reaches face 1 first -> weight error wins.
    joints = [(JOINT, 0, 0, 0)] * 15
    weights = [(1.0, 0.0, 0.0, 0.0)] * 15
    weights[4] = (math.nan, 0.0, 0.0, 0.0)
    indices = list(range(15))
    indices[12] = 999
    for fn in (_select_eye_triangles_reference, _select_eye_triangles_vectorised):
        with pytest.raises(PhotorealP3Quest2EyeComponentError, match="weight is invalid"):
            fn(indices=indices, joints=joints, weights=weights, joint_index=JOINT)
    # Same face has both: index range is checked before weights.
    indices = list(range(15))
    indices[5] = 999  # face 1 now escapes AND references the bad weight at 4
    for fn in (_select_eye_triangles_reference, _select_eye_triangles_vectorised):
        with pytest.raises(PhotorealP3Quest2EyeComponentError, match="escapes vertex universe"):
            fn(indices=indices, joints=joints, weights=weights, joint_index=JOINT)


def test_irregular_universe_falls_back_to_reference_loop() -> None:
    # Ragged skinning tuple: the vectorised path declines, the public entry
    # point raises the loop's width error for the first face that touches it.
    joints = [(JOINT, 0, 0, 0)] * 6
    weights = [(1.0, 0.0, 0.0, 0.0)] * 5 + [(1.0, 0.0, 0.0)]
    indices = [0, 1, 2, 3, 4, 5]
    assert _select_eye_triangles_vectorised(indices=indices, joints=joints, weights=weights, joint_index=JOINT) is None
    with pytest.raises(PhotorealP3Quest2EyeComponentError, match="tuple width is invalid"):
        select_eye_triangles(indices=indices, joints=joints, weights=weights, joint_index=JOINT, minimum_faces=1)
    # Float-valued joints are not a regular integer universe either.
    assert _select_eye_triangles_vectorised(
        indices=indices, joints=[(23.0, 0.0, 0.0, 0.0)] * 6, weights=[(1.0, 0.0, 0.0, 0.0)] * 6, joint_index=JOINT
    ) is None


@pytest.mark.parametrize(
    "third, expected",
    [
        (FACE_EYE_WEIGHT_THRESHOLD, [0]),               # mean exactly on the threshold
        (FACE_EYE_WEIGHT_THRESHOLD - 1e-10, []),        # a hair below: rejected by both
        (VERTEX_EYE_WEIGHT_THRESHOLD - 1e-10, []),      # one vertex just under its threshold
    ],
)
def test_threshold_boundaries_agree(third: float, expected: list[int]) -> None:
    joints = [(JOINT, 0, 0, 0)] * 3
    weights = [
        (FACE_EYE_WEIGHT_THRESHOLD, 0.0, 0.0, 0.0),
        (FACE_EYE_WEIGHT_THRESHOLD, 0.0, 0.0, 0.0),
        (third, 0.0, 0.0, 0.0),
    ]
    fast, slow = _both(indices=[0, 1, 2], joints=joints, weights=weights, joint_index=JOINT)
    assert fast == slow == expected
