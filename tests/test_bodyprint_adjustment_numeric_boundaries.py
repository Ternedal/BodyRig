from __future__ import annotations

import pytest

from bodyrig.bridges.bodyprint_shape_adjust import (
    ADJUSTMENT_FORMAT,
    FIELD_LIMITS,
    BodyprintAdjustmentError,
    validate_adjustment_payload,
)


def _payload(*, version: object = 1, delta: object = 0.005, field: str = "shape.shoulder_to_height") -> dict[str, object]:
    return {
        "format": ADJUSTMENT_FORMAT,
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


class _SingleFloat(float):
    def __new__(cls, value: float):
        instance = super().__new__(cls, value)
        instance.float_calls = 0
        return instance

    def __float__(self) -> float:
        self.float_calls += 1
        if self.float_calls > 1:
            raise AssertionError("delta was converted more than once")
        return super().__float__()


class _ValueErrorFloat(float):
    def __float__(self) -> float:
        raise ValueError("conversion failed")


class _TypeErrorFloat(float):
    def __float__(self) -> float:
        raise TypeError("conversion failed")


def test_huge_delta_is_normalized_to_domain_error() -> None:
    with pytest.raises(BodyprintAdjustmentError, match=r"changes\[0\]\.delta must be finite"):
        validate_adjustment_payload(_payload(delta=10**400))


@pytest.mark.parametrize("delta", [_ValueErrorFloat(0.005), _TypeErrorFloat(0.005)])
def test_conversion_failures_are_normalized_to_domain_error(delta: float) -> None:
    with pytest.raises(BodyprintAdjustmentError, match=r"changes\[0\]\.delta must be finite"):
        validate_adjustment_payload(_payload(delta=delta))


def test_boolean_version_is_rejected() -> None:
    with pytest.raises(BodyprintAdjustmentError, match="unsupported BodyPrint adjustment format/version"):
        validate_adjustment_payload(_payload(version=True))


def test_numeric_float_version_preserves_json_const_equality() -> None:
    validated = validate_adjustment_payload(_payload(version=1.0))
    assert validated["version"] == 1


@pytest.mark.parametrize("field,limit", FIELD_LIMITS.items())
@pytest.mark.parametrize("sign", [-1.0, 1.0])
def test_exact_v1_delta_boundaries_remain_valid(field: str, limit: float, sign: float) -> None:
    validated = validate_adjustment_payload(_payload(field=field, delta=sign * limit))
    assert validated["changes"][0]["field"] == field
    assert validated["changes"][0]["delta"] == sign * limit


def test_ordinary_delta_is_normalized_once_and_reused() -> None:
    delta = _SingleFloat(0.005)
    validated = validate_adjustment_payload(_payload(delta=delta))
    assert validated["changes"][0]["delta"] == 0.005
    assert type(validated["changes"][0]["delta"]) is float
    assert delta.float_calls == 1


def test_zero_delta_remains_rejected() -> None:
    with pytest.raises(BodyprintAdjustmentError, match="exceeds the bounded V1 limit"):
        validate_adjustment_payload(_payload(delta=0))
