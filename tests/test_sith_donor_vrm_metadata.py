from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest


BRIDGES = Path(__file__).resolve().parents[1] / "bodyrig" / "bridges"
if str(BRIDGES) not in sys.path:
    sys.path.insert(0, str(BRIDGES))

from sith_donor_vrm_metadata import (  # noqa: E402
    DonorVrmMetadataError,
    _finite_nonnegative_metric,
)


def test_donor_metric_accepts_finite_nonnegative_value() -> None:
    assert _finite_nonnegative_metric(0.125, label="metric") == 0.125
    assert _finite_nonnegative_metric(0, label="metric") == 0.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf"), -0.001, True, "0.1", None])
def test_donor_metric_rejects_invalid_values(value: object) -> None:
    with pytest.raises(DonorVrmMetadataError, match="metric is invalid"):
        _finite_nonnegative_metric(value, label="metric")


def test_donor_metric_result_is_finite() -> None:
    value = _finite_nonnegative_metric(1.0, label="metric")
    assert math.isfinite(value)
