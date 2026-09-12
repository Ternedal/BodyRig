from __future__ import annotations

import pytest

from bodyrig.bridges import bodyprint_shape_adjust as adjust


class CountingFloat(float):
    def __new__(cls, value: float):
        instance = super().__new__(cls, value)
        instance.float_calls = 0
        return instance

    def __float__(self) -> float:
        self.float_calls += 1
        return float.__float__(self)


def _payload(*, delta=0.01, version=1, field="shape.arm_to_height") -> dict:
    return {
        "format": adjust.ADJUSTMENT_FORMAT,
        "version": version,
        "feedback_sha256": "a" * 64,
        "changes": [
            {
                "field": field,
                "delta": delta,
                "reason": "source-grounded correction",
            }
        ],
    }


def test_huge_delta_fails_with_domain_error() -> None:
    with pytest.raises(adjust.BodyprintAdjustmentError, match=r"changes\[0\]\.delta must be finite"):
        adjust.validate_adjustment_payload(_payload(delta=10**400))


def test_boolean_version_is_rejected() -> None:
    with pytest.raises(adjust.BodyprintAdjustmentError, match="unsupported BodyPrint adjustment format/version"):
        adjust.validate_adjustment_payload(_payload(version=True))


def test_numeric_float_version_remains_v1_compatible() -> None:
    result = adjust.validate_adjustment_payload(_payload(version=1.0))

    assert result["version"] == adjust.ADJUSTMENT_VERSION
    assert result["changes"][0]["delta"] == 0.01


@pytest.mark.parametrize("delta", [-0.015, 0.015])
def test_exact_arm_delta_boundaries_are_accepted(delta) -> None:
    result = adjust.validate_adjustment_payload(_payload(delta=delta))

    assert result["changes"][0]["delta"] == delta
    assert type(result["changes"][0]["delta"]) is float


def test_accepted_delta_is_converted_exactly_once_and_normalized() -> None:
    delta = CountingFloat(0.01)

    result = adjust.validate_adjustment_payload(_payload(delta=delta))

    assert delta.float_calls == 1
    assert result["changes"][0]["delta"] == 0.01
    assert type(result["changes"][0]["delta"]) is float
