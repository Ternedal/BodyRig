from __future__ import annotations

import pytest

from bodyrig.skin_qa import (
    LEGACY_RIG_TRANSFER,
    SkinQaError,
    _finite,
    _validate_transfer_authority,
)


class _SingleFloatInt(int):
    def __new__(cls, value: int):
        instance = super().__new__(cls, value)
        instance.float_calls = 0
        return instance

    def __float__(self) -> float:
        self.float_calls += 1
        if self.float_calls > 1:
            raise AssertionError("numeric value was converted more than once")
        return super().__float__()


def _legacy_transfer(p95: object, maximum: object) -> dict[str, object]:
    return {
        "rigTransfer": {
            "method": LEGACY_RIG_TRANSFER,
            "nearestDistanceP95": p95,
            "nearestDistanceMax": maximum,
        }
    }


def test_donor_appearance_numeric_overflow_is_skin_qa_error() -> None:
    with pytest.raises(SkinQaError, match="donor appearance"):
        _finite(10**400, label="boundary", minimum=0.0)


def test_donor_appearance_normal_integer_and_float_values_survive() -> None:
    assert _finite(1, label="boundary", minimum=0.0, maximum=1.0) == 1.0
    assert _finite(0.25, label="boundary", minimum=0.0, maximum=1.0) == 0.25


@pytest.mark.parametrize("field", ["nearestDistanceP95", "nearestDistanceMax"])
def test_rig_transfer_huge_integer_is_skin_qa_error(field: str) -> None:
    bodyrig = _legacy_transfer(0.0, 0.0)
    bodyrig["rigTransfer"][field] = 10**400  # type: ignore[index]
    with pytest.raises(SkinQaError, match="rig transfer distance"):
        _validate_transfer_authority(bodyrig)


@pytest.mark.parametrize("field", ["nearestDistanceP95", "nearestDistanceMax"])
def test_rig_transfer_boolean_is_rejected(field: str) -> None:
    bodyrig = _legacy_transfer(0.0, 0.0)
    bodyrig["rigTransfer"][field] = True  # type: ignore[index]
    with pytest.raises(SkinQaError, match="rig transfer distance"):
        _validate_transfer_authority(bodyrig)


def test_rig_transfer_values_are_normalized_once_and_reused() -> None:
    p95 = _SingleFloatInt(1)
    maximum = _SingleFloatInt(2)
    method, normalized_p95, normalized_max = _validate_transfer_authority(_legacy_transfer(p95, maximum))
    assert method == LEGACY_RIG_TRANSFER
    assert normalized_p95 == 1.0
    assert normalized_max == 2.0
    assert p95.float_calls == 1
    assert maximum.float_calls == 1
