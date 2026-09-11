from pathlib import Path

repo = Path.cwd()
shim = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
raw_ranges = repo / "tests" / "test_reference_renderer_raw_numeric_ranges.py"
whitespace = repo / "tests" / "test_reference_renderer_json_whitespace_guard.py"
parity = repo / "tests" / "test_reference_renderer_integer_number_schema_parity.py"

shim_source = shim.read_text(encoding="utf-8")
if "JsonIntegerPattern" in shim_source:
    raise SystemExit("core patch did not remove JsonIntegerPattern")
if "private static bool IsIntegralJsonNumber(string raw)" not in shim_source:
    raise SystemExit("core patch did not add IsIntegralJsonNumber")
if "CompareJsonNumberToInteger(raw, minimum) < 0" not in shim_source:
    raise SystemExit("core patch did not switch integer range comparison")

ranges_source = raw_ranges.read_text(encoding="utf-8")
if "IsIntegralJsonNumber(raw)" not in ranges_source:
    raise SystemExit("core patch did not update raw numeric range contract")


def replace_test_function(source: str, name: str, replacement: str) -> str:
    start_marker = f"def {name}() -> None:"
    start = source.find(start_marker)
    if start < 0:
        raise SystemExit(f"missing test function: {name}")
    next_start = source.find("\ndef ", start + len(start_marker))
    if next_start < 0:
        return source[:start] + replacement.rstrip() + "\n"
    return source[:start] + replacement.rstrip() + "\n\n" + source[next_start + 1 :]


whitespace_source = whitespace.read_text(encoding="utf-8")
old_assert = '    assert "Regex.IsMatch(raw, \\\"^(?:\\\" + JsonIntegerPattern" in numeric\n'
if whitespace_source.count(old_assert) != 1:
    raise SystemExit(f"whitespace JsonIntegerPattern assertion count={whitespace_source.count(old_assert)}")
whitespace_source = whitespace_source.replace(
    old_assert,
    '    assert "JsonIntegerPattern" not in numeric\n'
    '    assert "RequireNumericToken(raw, context);" in numeric\n',
    1,
)
whitespace_source = replace_test_function(
    whitespace_source,
    "test_raw_integer_ranges_are_checked_before_unity_int_coercion",
    '''def test_raw_integer_ranges_are_checked_before_unity_int_coercion() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[
        source.index("private static void RequireIntegerToken") :
        source.index("private static void RequireExactFields")
    ]
    assert "RequireNumericToken(raw, context);" in helper
    assert "IsIntegralJsonNumber(raw)" in helper
    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in helper
    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in helper
    assert "long.TryParse(\\n                    raw," not in helper
    assert "ArgumentOutOfRangeException" in helper''',
)
whitespace.write_text(whitespace_source, encoding="utf-8")

if parity.exists():
    raise SystemExit("integer number schema parity regression already exists")
parity.write_text('''from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]


def test_all_motor_state_schemas_define_same_integer_fields_and_ranges() -> None:
    for path in SCHEMAS:
        schema = json.loads(path.read_text(encoding="utf-8"))
        duration = schema["properties"]["duration_ms"]
        elapsed = schema["properties"]["speech"]["properties"]["elapsed_ms"]
        assert duration["type"] == "integer"
        assert duration["minimum"] == 0
        assert duration["maximum"] == 120000
        assert elapsed["type"] == "integer"
        assert elapsed["minimum"] == 0
        assert elapsed["maximum"] == 3600000


def test_renderer_integer_guard_accepts_exact_integral_number_semantics_without_float_coercion() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[
        source.index("private static void RequireIntegerToken") :
        source.index("private static void RequireExactFields")
    ]
    assert "RequireNumericToken(raw, context);" in helper
    assert "IsIntegralJsonNumber(raw)" in helper
    assert "fractionalDigits" in helper
    assert "explicitExponent" in helper
    assert "SaturatingSubtract(explicitExponent, fractionalDigits)" in helper
    assert "lastNonZeroDigitIndex" in helper
    assert "requiredTrailingZeros = -exponent10" in helper
    assert "trailingZeros >= requiredTrailingZeros" in helper
    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in helper
    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in helper
    for parser in (
        "float.Parse",
        "double.Parse",
        "decimal.Parse",
        "float.TryParse",
        "double.TryParse",
        "decimal.TryParse",
    ):
        assert parser not in helper


def test_integer_guard_retains_canonical_json_number_syntax_authority() -> None:
    source = SHIM.read_text(encoding="utf-8")
    numeric = source[
        source.index("private static void RequireNumericToken") :
        source.index("private static void RequireNumericRangeToken")
    ]
    assert "JsonNumberPattern" in numeric
    assert "RegexOptions.CultureInvariant" in numeric
    assert "JsonIntegerPattern" not in source
''', encoding="utf-8")
