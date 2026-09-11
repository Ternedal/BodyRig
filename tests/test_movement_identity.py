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
            "posture_shoulder_tilt_degrees": 1.4,
            "posture_hip_tilt_degrees": 0.9,
            "posture_head_offset_to_height": 0.045,
            "walk_cadence_spm": 112.0,
            "stride_length_to_height": 0.34,
            "stance_width_to_height": 0.13,
            "vertical_bounce_to_height": 0.025,
            "arm_swing_to_height": 0.18,
            "arm_swing_asymmetry": 0.08,
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
