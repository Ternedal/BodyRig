from __future__ import annotations

import pytest

from bodyrig.bridges.sith_anatomy_guard import classify_strong_limb_regions


NAMES = (
    "pelvis",
    "left_hip",
    "right_hip",
    "left_shoulder",
    "right_shoulder",
    "left_wrist",
    "right_wrist",
    "left_ankle",
    "right_ankle",
)
PARENTS = (-1, 0, 0, 0, 0, 3, 4, 1, 2)
JOINTS = (
    (0.0, 1.0, 0.0),
    (-0.25, 0.9, 0.0),
    (0.25, 0.9, 0.0),
    (-0.35, 1.55, 0.0),
    (0.35, 1.55, 0.0),
    (-0.75, 1.2, 0.0),
    (0.75, 1.2, 0.0),
    (-0.25, 0.0, 0.0),
    (0.25, 0.0, 0.0),
)


class FloatOnce:
    def __init__(self, value: float) -> None:
        self.value = value
        self.calls = 0

    def __float__(self) -> float:
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("coordinate was coerced more than once")
        return self.value


def test_joint_coordinate_conversion_overflow_normalizes_to_anatomy_guard_error() -> None:
    joints = list(JOINTS)
    joints[0] = (10**400, 1.0, 0.0)

    with pytest.raises(ValueError, match="^anatomy guard joint coordinates are invalid$"):
        classify_strong_limb_regions([(0.25, 0.45, 0.02)], joints, PARENTS, NAMES)


def test_joint_scale_arithmetic_overflow_normalizes_to_anatomy_guard_error() -> None:
    joints = list(JOINTS)
    joints[0] = (1e200, 1.0, 0.0)

    with pytest.raises(ValueError, match="^anatomy guard skeleton scale is invalid$"):
        classify_strong_limb_regions([(0.25, 0.45, 0.02)], joints, PARENTS, NAMES)


def test_reconstructed_vertex_conversion_overflow_normalizes_to_anatomy_guard_error() -> None:
    with pytest.raises(ValueError, match="^anatomy guard reconstructed vertex is non-finite$"):
        classify_strong_limb_regions([(10**400, 0.45, 0.02)], JOINTS, PARENTS, NAMES)


def test_reconstructed_vertex_distance_overflow_normalizes_to_anatomy_guard_error() -> None:
    with pytest.raises(ValueError, match="^anatomy guard reconstructed vertex is non-finite$"):
        classify_strong_limb_regions([(1e200, 0.45, 0.02)], JOINTS, PARENTS, NAMES)


def test_ordinary_geometry_preserves_region_classification() -> None:
    regions, body_scale = classify_strong_limb_regions(
        [(0.25, 0.45, 0.02), (0.0, 1.0, 0.0)],
        JOINTS,
        PARENTS,
        NAMES,
    )

    assert body_scale > 1.0
    assert regions == ["right_leg", None]


def test_accepted_coordinates_are_coerced_exactly_once() -> None:
    wrapped_joints = tuple(
        tuple(FloatOnce(value) for value in row)
        for row in JOINTS
    )
    wrapped_point = tuple(FloatOnce(value) for value in (0.25, 0.45, 0.02))

    regions, body_scale = classify_strong_limb_regions(
        [wrapped_point],
        wrapped_joints,
        PARENTS,
        NAMES,
    )

    assert body_scale > 1.0
    assert regions == ["right_leg"]
    assert all(value.calls == 1 for row in wrapped_joints for value in row)
    assert all(value.calls == 1 for value in wrapped_point)
