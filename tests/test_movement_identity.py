from __future__ import annotations

import pytest

from bodyrig.movement_identity import MovementIdentityError, inspect_movement_identity, require_movement_identity
from bodyrig.package import MRBodyError, validate_bodyprint


def _bodyprint() -> dict:
    return {
        "format": "modelrig-bodyprint",
        "version": 1,
        "motion": {
            "energy": 0.42,
            "movement_observed_frames": 48,
            "movement_observed_seconds": 3.8,
            "gait_step_events": 6,
            "idle_observed_seconds": 0.8,
            "posture_torso_lean_degrees": 5.2,
            "posture_torso_forward_lean_degrees": 4.8,
            "posture_torso_right_lean_degrees": -1.2,
            "posture_shoulder_tilt_degrees": 1.4,
            "posture_shoulder_roll_degrees": -1.4,
            "posture_hip_tilt_degrees": 0.9,
            "posture_hip_roll_degrees": 0.9,
            "posture_head_offset_to_height": 0.045,
            "posture_head_forward_offset_to_height": 0.041,
            "posture_head_right_offset_to_height": 0.018,
            "walk_cadence_spm": 112.0,
            "stride_length_to_height": 0.34,
            "stance_width_to_height": 0.13,
            "vertical_bounce_to_height": 0.025,
            "left_arm_swing_to_height": 0.19,
            "right_arm_swing_to_height": 0.17,
            "arm_swing_to_height": 0.18,
            "arm_swing_asymmetry": 0.1053,
            "turn_speed": 0.22,
            "turn_speed_degrees_per_second": 39.6,
            "transition_intensity": 0.31,
            "idle_sway_to_height": 0.012,
        },
    }


def test_complete_source_derived_movement_identity_passes() -> None:
    result = require_movement_identity(_bodyprint())
    assert result["complete"] is True
    assert result["missing_fields"] == []
    assert result["coverage"]["gait_step_events"] == 6


def test_integral_float_counts_from_multisource_aggregation_remain_valid() -> None:
    bodyprint = _bodyprint()
    bodyprint["motion"]["movement_observed_frames"] = 48.0
    bodyprint["motion"]["gait_step_events"] = 6.0
    validate_bodyprint(bodyprint)
    assert require_movement_identity(bodyprint)["complete"] is True


def test_fractional_observation_counts_are_rejected() -> None:
    bodyprint = _bodyprint()
    bodyprint["motion"]["gait_step_events"] = 6.5
    with pytest.raises(MRBodyError, match="integral observation count"):
        validate_bodyprint(bodyprint)
    assert inspect_movement_identity(bodyprint)["complete"] is False


def test_missing_gait_cannot_be_called_complete() -> None:
    bodyprint = _bodyprint()
    del bodyprint["motion"]["walk_cadence_spm"]
    del bodyprint["motion"]["stride_length_to_height"]
    result = inspect_movement_identity(bodyprint)
    assert result["complete"] is False
    assert "walk_cadence_spm" in result["missing_fields"]
    with pytest.raises(MovementIdentityError, match="Movement Identity is incomplete"):
        require_movement_identity(bodyprint)


def test_unsigned_arm_swing_summary_cannot_prove_anatomical_direction() -> None:
    bodyprint = _bodyprint()
    del bodyprint["motion"]["left_arm_swing_to_height"]
    del bodyprint["motion"]["right_arm_swing_to_height"]

    result = inspect_movement_identity(bodyprint)
    assert result["complete"] is False
    assert "left_arm_swing_to_height" in result["missing_fields"]
    assert "right_arm_swing_to_height" in result["missing_fields"]
    with pytest.raises(MovementIdentityError, match="Movement Identity is incomplete"):
        require_movement_identity(bodyprint)


def test_magnitude_only_posture_cannot_be_called_complete() -> None:
    bodyprint = _bodyprint()
    for field in (
        "posture_torso_forward_lean_degrees",
        "posture_torso_right_lean_degrees",
        "posture_shoulder_roll_degrees",
        "posture_hip_roll_degrees",
        "posture_head_forward_offset_to_height",
        "posture_head_right_offset_to_height",
    ):
        del bodyprint["motion"][field]

    result = inspect_movement_identity(bodyprint)
    assert result["complete"] is False
    assert "posture_torso_forward_lean_degrees" in result["missing_fields"]
    assert "posture_head_right_offset_to_height" in result["missing_fields"]
    with pytest.raises(MovementIdentityError, match="Movement Identity is incomplete"):
        require_movement_identity(bodyprint)


def test_signed_posture_ranges_are_fail_closed() -> None:
    bodyprint = _bodyprint()
    bodyprint["motion"]["posture_torso_right_lean_degrees"] = -91.0
    with pytest.raises(MRBodyError, match="posture_torso_right_lean_degrees"):
        validate_bodyprint(bodyprint)
    result = inspect_movement_identity(bodyprint)
    assert result["complete"] is False
    assert any("posture_torso_right_lean_degrees" in blocker for blocker in result["blockers"])


def test_short_or_nonwalking_evidence_fails_closed() -> None:
    bodyprint = _bodyprint()
    bodyprint["motion"]["movement_observed_frames"] = 12
    bodyprint["motion"]["movement_observed_seconds"] = 0.9
    bodyprint["motion"]["gait_step_events"] = 1
    bodyprint["motion"]["idle_observed_seconds"] = 0.2
    result = inspect_movement_identity(bodyprint)
    assert result["complete"] is False
    assert any("frames=12/24" in item for item in result["blockers"])
    assert any("step_events=1/2" in item for item in result["blockers"])
    assert any("idle evidence is incomplete" in item for item in result["blockers"])


def test_implausible_cadence_is_not_identity_authority() -> None:
    bodyprint = _bodyprint()
    bodyprint["motion"]["walk_cadence_spm"] = 280.0
    result = inspect_movement_identity(bodyprint)
    assert result["complete"] is False
    assert any("cadence is implausible" in item for item in result["blockers"])


def test_huge_numeric_field_fails_closed_as_movement_identity_error() -> None:
    bodyprint = _bodyprint()
    bodyprint["motion"]["walk_cadence_spm"] = 10**400

    result = inspect_movement_identity(bodyprint)
    assert result["complete"] is False
    assert any("walk_cadence_spm" in blocker for blocker in result["blockers"])

    with pytest.raises(MovementIdentityError, match="walk_cadence_spm"):
        require_movement_identity(bodyprint)


def test_numeric_range_boundaries_remain_valid() -> None:
    bodyprint = _bodyprint()
    bodyprint["motion"]["posture_torso_forward_lean_degrees"] = -90.0
    bodyprint["motion"]["posture_torso_right_lean_degrees"] = 90.0
    bodyprint["motion"]["posture_shoulder_roll_degrees"] = -90.0
    bodyprint["motion"]["posture_hip_roll_degrees"] = 90.0
    bodyprint["motion"]["posture_head_forward_offset_to_height"] = -1.0
    bodyprint["motion"]["posture_head_right_offset_to_height"] = 1.0
    bodyprint["motion"]["turn_speed_degrees_per_second"] = 720.0
    bodyprint["motion"]["transition_intensity"] = 1.0
    bodyprint["motion"]["idle_sway_to_height"] = 0.0

    assert require_movement_identity(bodyprint)["complete"] is True
