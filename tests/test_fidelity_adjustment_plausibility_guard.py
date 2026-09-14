from __future__ import annotations

import copy

import pytest

from bodyrig.fidelity_adjustment import (
    FidelityAdjustmentError,
    SEMANTICS,
    build_fidelity_adjustment_plan,
)


def _evaluation() -> dict[str, object]:
    return {
        "format": "bodyrig-fidelity-evaluation",
        "version": 1,
        "semantics": SEMANTICS,
        "measurement": {"scores": {"overall": 0.21}},
        "shape_hint": {
            "shoulder_direction": "wider",
            "hip_direction": "wider",
            "shoulder_profile_delta": 0.45,
            "hip_profile_delta": 0.47,
        },
        "plausibility": {
            "head_shoulder_ratio": 0.55,
        },
    }


def test_plausible_silhouette_keeps_bounded_shape_adjustment() -> None:
    plan = build_fidelity_adjustment_plan(_evaluation())

    assert plan["applicable"] is True
    assert plan["feedback"] == "shoulders should be wider; hips should be wider"
    assert plan["adjustment_request"] is not None


def test_grossly_implausible_head_shoulder_ratio_suppresses_automatic_shape_edit() -> None:
    evaluation = _evaluation()
    evaluation["plausibility"]["head_shoulder_ratio"] = 1.45

    plan = build_fidelity_adjustment_plan(evaluation)

    assert plan["applicable"] is False
    assert plan["adjustment_request"] is None
    assert "suppressed" in plan["feedback"]
    assert "trusted range" in plan["feedback"]


def test_legacy_evaluation_without_plausibility_preserves_historical_behavior() -> None:
    evaluation = _evaluation()
    del evaluation["plausibility"]

    plan = build_fidelity_adjustment_plan(evaluation)

    assert plan["applicable"] is True
    assert plan["adjustment_request"] is not None


@pytest.mark.parametrize("bad", [True, False, "1.45", None, float("nan"), float("inf"), -0.1])
def test_malformed_head_shoulder_ratio_fails_closed(bad: object) -> None:
    evaluation = copy.deepcopy(_evaluation())
    evaluation["plausibility"]["head_shoulder_ratio"] = bad

    with pytest.raises(FidelityAdjustmentError, match="head_shoulder_ratio"):
        build_fidelity_adjustment_plan(evaluation)
