from __future__ import annotations

from bodyrig import skin_qa
from bodyrig.bridges.sith_anatomy_guard import (
    ANATOMY_GUARD_THRESHOLD,
    classify_strong_limb_regions,
    forbidden_joint_indices,
    forbidden_regions,
    joint_region,
)


def test_prefixed_smplx_joint_names_share_skin_qa_region_authority():
    assert joint_region("smplx_left_hip") == "left_leg"
    assert joint_region("smplx_right_knee") == "right_leg"
    assert joint_region("smplx_left_wrist") == "left_arm"
    assert joint_region("smplx_right_shoulder") == "right_arm"
    assert joint_region("smplx_pelvis") == "torso"
    assert skin_qa._region("smplx_left_hip") == "left_leg"
    assert skin_qa._region("smplx_right_hip") == "right_leg"
    assert skin_qa._forbidden("right_leg") == forbidden_regions("right_leg")
    assert ANATOMY_GUARD_THRESHOLD == skin_qa.SUSPICIOUS_WEIGHT


def test_right_leg_forbidden_joint_set_allows_pelvis_and_right_leg():
    names = (
        "pelvis",
        "left_hip",
        "right_hip",
        "left_shoulder",
        "right_shoulder",
        "left_knee",
        "right_knee",
    )
    indices = set(forbidden_joint_indices(names, "right_leg"))
    assert indices == {1, 3, 4, 5}
    assert 0 not in indices
    assert 2 not in indices
    assert 6 not in indices


def test_geometry_classifies_strong_right_leg_without_cross_midline_guessing():
    names = (
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
    parents = (-1, 0, 0, 0, 0, 3, 4, 1, 2)
    joints = (
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
    regions, body_scale = classify_strong_limb_regions(
        [(0.25, 0.45, 0.02), (0.0, 1.0, 0.0)],
        joints,
        parents,
        names,
    )
    assert body_scale > 1.0
    assert regions[0] == "right_leg"
    assert regions[1] is None
