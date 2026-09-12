from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from bodyrig.package import MRBodyError, validate_bodyprint


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / "contracts" / "bodyprint-v1.schema.json").read_text(encoding="utf-8"))


def _bodyprint(value: object) -> dict[str, object]:
    return {
        "format": "modelrig-bodyprint",
        "version": 1,
        "shape": {"height_scale": value},
    }


def test_height_scale_accepts_schema_valid_tiny_positive_value() -> None:
    field = SCHEMA["properties"]["shape"]["properties"]["height_scale"]
    assert field["exclusiveMinimum"] == 0
    assert field["maximum"] == 4
    value = 5e-7
    assert 0 < value < 1e-6
    assert validate_bodyprint(_bodyprint(value))["shape"]["height_scale"] == value


def test_height_scale_accepts_schema_maximum() -> None:
    maximum = SCHEMA["properties"]["shape"]["properties"]["height_scale"]["maximum"]
    assert maximum == 4
    assert validate_bodyprint(_bodyprint(maximum))["shape"]["height_scale"] == maximum


@pytest.mark.parametrize("value", [0.0, -1e-9, True, float("inf"), float("-inf"), float("nan")])
def test_height_scale_rejects_values_outside_schema_number_contract(value: object) -> None:
    with pytest.raises(MRBodyError, match=r"bodyprint\.shape\.height_scale: invalid number"):
        validate_bodyprint(_bodyprint(value))


def test_height_scale_nan_case_is_actually_non_finite() -> None:
    assert not math.isfinite(float("nan"))
