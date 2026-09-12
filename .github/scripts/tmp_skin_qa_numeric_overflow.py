from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one replacement target, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


skin = Path("bodyrig/skin_qa.py")
replace_once(
    skin,
    '''    result = float(value)\n    if not math.isfinite(result):\n        raise SkinQaError(f"skin QA: donor appearance {label} evidence is invalid")\n''',
    '''    try:\n        result = float(value)\n    except (TypeError, ValueError, OverflowError):\n        raise SkinQaError(f"skin QA: donor appearance {label} evidence is invalid") from None\n    if not math.isfinite(result):\n        raise SkinQaError(f"skin QA: donor appearance {label} evidence is invalid")\n''',
)
replace_once(
    skin,
    '''def _positive_int(value: Any, *, label: str) -> int:\n''',
    '''def _rig_transfer_distance(value: Any) -> float:\n    if isinstance(value, bool) or not isinstance(value, (int, float)):\n        raise SkinQaError("skin QA: rig transfer distance evidence is invalid")\n    try:\n        result = float(value)\n    except (TypeError, ValueError, OverflowError):\n        raise SkinQaError("skin QA: rig transfer distance evidence is invalid") from None\n    if not math.isfinite(result) or result < 0.0:\n        raise SkinQaError("skin QA: rig transfer distance evidence is invalid")\n    return result\n\n\ndef _positive_int(value: Any, *, label: str) -> int:\n''',
)
replace_once(
    skin,
    '''    nearest_p95 = transfer.get("nearestDistanceP95")\n    nearest_max = transfer.get("nearestDistanceMax")\n    if any(\n        isinstance(value, bool)\n        or not isinstance(value, (int, float))\n        or not math.isfinite(float(value))\n        or float(value) < 0.0\n        for value in (nearest_p95, nearest_max)\n    ):\n        raise SkinQaError("skin QA: rig transfer distance evidence is invalid")\n\n    if method == LEGACY_RIG_TRANSFER:\n        return str(method), float(nearest_p95), float(nearest_max)\n\n    if float(nearest_p95) != 0.0 or float(nearest_max) != 0.0:\n''',
    '''    nearest_p95 = _rig_transfer_distance(transfer.get("nearestDistanceP95"))\n    nearest_max = _rig_transfer_distance(transfer.get("nearestDistanceMax"))\n\n    if method == LEGACY_RIG_TRANSFER:\n        return str(method), nearest_p95, nearest_max\n\n    if nearest_p95 != 0.0 or nearest_max != 0.0:\n''',
)

tests = Path("tests/test_skin_qa_numeric_boundaries.py")
tests.write_text('''from __future__ import annotations\n\nimport pytest\n\nfrom bodyrig.skin_qa import (\n    LEGACY_RIG_TRANSFER,\n    SkinQaError,\n    _finite,\n    _validate_transfer_authority,\n)\n\n\nclass _SingleFloatInt(int):\n    def __new__(cls, value: int):\n        instance = super().__new__(cls, value)\n        instance.float_calls = 0\n        return instance\n\n    def __float__(self) -> float:\n        self.float_calls += 1\n        if self.float_calls > 1:\n            raise AssertionError("numeric value was converted more than once")\n        return super().__float__()\n\n\ndef _legacy_transfer(p95: object, maximum: object) -> dict[str, object]:\n    return {\n        "rigTransfer": {\n            "method": LEGACY_RIG_TRANSFER,\n            "nearestDistanceP95": p95,\n            "nearestDistanceMax": maximum,\n        }\n    }\n\n\ndef test_donor_appearance_numeric_overflow_is_skin_qa_error() -> None:\n    with pytest.raises(SkinQaError, match="donor appearance"):\n        _finite(10**400, label="boundary", minimum=0.0)\n\n\ndef test_donor_appearance_normal_integer_and_float_values_survive() -> None:\n    assert _finite(1, label="boundary", minimum=0.0, maximum=1.0) == 1.0\n    assert _finite(0.25, label="boundary", minimum=0.0, maximum=1.0) == 0.25\n\n\n@pytest.mark.parametrize("field", ["nearestDistanceP95", "nearestDistanceMax"])\ndef test_rig_transfer_huge_integer_is_skin_qa_error(field: str) -> None:\n    bodyrig = _legacy_transfer(0.0, 0.0)\n    bodyrig["rigTransfer"][field] = 10**400  # type: ignore[index]\n    with pytest.raises(SkinQaError, match="rig transfer distance"):\n        _validate_transfer_authority(bodyrig)\n\n\n@pytest.mark.parametrize("field", ["nearestDistanceP95", "nearestDistanceMax"])\ndef test_rig_transfer_boolean_is_rejected(field: str) -> None:\n    bodyrig = _legacy_transfer(0.0, 0.0)\n    bodyrig["rigTransfer"][field] = True  # type: ignore[index]\n    with pytest.raises(SkinQaError, match="rig transfer distance"):\n        _validate_transfer_authority(bodyrig)\n\n\ndef test_rig_transfer_values_are_normalized_once_and_reused() -> None:\n    p95 = _SingleFloatInt(1)\n    maximum = _SingleFloatInt(2)\n    method, normalized_p95, normalized_max = _validate_transfer_authority(_legacy_transfer(p95, maximum))\n    assert method == LEGACY_RIG_TRANSFER\n    assert normalized_p95 == 1.0\n    assert normalized_max == 2.0\n    assert p95.float_calls == 1\n    assert maximum.float_calls == 1\n''', encoding="utf-8")
