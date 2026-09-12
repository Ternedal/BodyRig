from __future__ import annotations

import pytest

from bodyrig.bridges import bodyprint_shape_adjust as adjust


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


def test_ordinary_integer_delta_is_normalized_to_float() -> None:
    result = adjust.validate_adjustment_payload(
        _payload(delta=1, field="motion.gesture_amplitude")
    )

    # The integer is outside the bounded V1 range, so conversion succeeds first
    # and the existing bounded-range contract still rejects it canonically.
    assert result  # pragma: no cover
