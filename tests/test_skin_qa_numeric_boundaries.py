from __future__ import annotations

import pytest

from bodyrig.skin_qa import LEGACY_RIG_TRANSFER, SkinQaError, _finite, _validate_transfer_authority


def _legacy_transfer(*, p95: object = 0.012, maximum: object = 0.031) -> dict[str, object]:
    return {
        "rigTransfer": {
            "method": LEGACY_RIG_TRANSFER,
            "nearestDistanceP95": p95,
            "nearestDistanceMax": maximum,
        }
    }


def test_finite_normalizes_arbitrary_precision_overflow() -> None:
    with pytest.raises(SkinQaError, match="donor appearance body scale evidence is invalid"):
        _finite(10**400, label="body scale", minimum=0.0)


def test_finite_preserves_ordinary_numeric_values() -> None:
    assert _finite(1, label="body scale", minimum=0.0) == 1.0
    assert _finite(0.5, label="ratio", minimum=0.0, maximum=1.0) == 0.5


@pytest.mark.parametrize("field", ["p95", "maximum"])
def test_transfer_distance_normalizes_arbitrary_precision_overflow(field: str) -> None:
    values = {"p95": 0.012, "maximum": 0.031}
    values[field] = 10**400
    with pytest.raises(SkinQaError, match="rig transfer distance evidence is invalid"):
        _validate_transfer_authority(_legacy_transfer(**values))


@pytest.mark.parametrize("field", ["p95", "maximum"])
def test_transfer_distance_rejects_boolean_values(field: str) -> None:
    values = {"p95": 0.012, "maximum": 0.031}
    values[field] = True
    with pytest.raises(SkinQaError, match="rig transfer distance evidence is invalid"):
        _validate_transfer_authority(_legacy_transfer(**values))


def test_legacy_transfer_preserves_normalized_numeric_values() -> None:
    method, p95, maximum = _validate_transfer_authority(_legacy_transfer(p95=1, maximum=2.5))
    assert method == LEGACY_RIG_TRANSFER
    assert p95 == 1.0
    assert maximum == 2.5
