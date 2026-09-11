from pathlib import Path

repo = Path.cwd()
shim = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
source = shim.read_text(encoding="utf-8")

integer_pattern = '        private const string JsonIntegerPattern = "-?(?:0|[1-9][0-9]*)";\n'
if source.count(integer_pattern) != 1:
    raise SystemExit(f"JsonIntegerPattern anchor count={source.count(integer_pattern)}")
source = source.replace(integer_pattern, "", 1)

old = '''        private static void RequireIntegerToken(string raw, string context)
        {
            if (!Regex.IsMatch(raw, "^(?:" + JsonIntegerPattern + ")$", RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} requires an integer JSON token");
            }
        }

        private static void RequireIntegerRangeToken(
            string raw,
            string context,
            long minimum,
            long maximum)
        {
            RequireIntegerToken(raw, context);
            if (!long.TryParse(
                    raw,
                    NumberStyles.AllowLeadingSign,
                    CultureInfo.InvariantCulture,
                    out var value) ||
                value < minimum || value > maximum)
            {
                throw new ArgumentOutOfRangeException(
                    context,
                    $"Motor State integer value must be in {minimum}..{maximum}");
            }
        }
'''
new = '''        private static void RequireIntegerToken(string raw, string context)
        {
            RequireNumericToken(raw, context);
            if (!IsIntegralJsonNumber(raw))
            {
                throw new ArgumentException($"Motor State {context} requires an integer-valued JSON number");
            }
        }

        private static bool IsIntegralJsonNumber(string raw)
        {
            var cursor = raw[0] == '-' ? 1 : 0;
            var exponentIndex = raw.IndexOf('e', cursor);
            if (exponentIndex < 0)
            {
                exponentIndex = raw.IndexOf('E', cursor);
            }
            var mantissaEnd = exponentIndex >= 0 ? exponentIndex : raw.Length;
            var dotIndex = raw.IndexOf('.', cursor, mantissaEnd - cursor);
            var fractionalDigits = dotIndex >= 0 ? mantissaEnd - dotIndex - 1 : 0;

            var digitCount = 0;
            var lastNonZeroDigitIndex = -1;
            for (var index = cursor; index < mantissaEnd; index++)
            {
                if (raw[index] == '.') continue;
                if (raw[index] != '0') lastNonZeroDigitIndex = digitCount;
                digitCount++;
            }
            if (lastNonZeroDigitIndex < 0)
            {
                return true;
            }

            long explicitExponent = 0L;
            if (exponentIndex >= 0)
            {
                var exponentToken = raw.Substring(exponentIndex + 1);
                if (!long.TryParse(
                        exponentToken,
                        NumberStyles.AllowLeadingSign,
                        CultureInfo.InvariantCulture,
                        out explicitExponent))
                {
                    explicitExponent = exponentToken[0] == '-' ? long.MinValue : long.MaxValue;
                }
            }
            var exponent10 = SaturatingSubtract(explicitExponent, fractionalDigits);
            if (exponent10 >= 0L)
            {
                return true;
            }
            if (exponent10 == long.MinValue)
            {
                return false;
            }

            var requiredTrailingZeros = -exponent10;
            var trailingZeros = (long)digitCount - lastNonZeroDigitIndex - 1L;
            return trailingZeros >= requiredTrailingZeros;
        }

        private static void RequireIntegerRangeToken(
            string raw,
            string context,
            long minimum,
            long maximum)
        {
            RequireIntegerToken(raw, context);
            if (CompareJsonNumberToInteger(raw, minimum) < 0 ||
                CompareJsonNumberToInteger(raw, maximum) > 0)
            {
                throw new ArgumentOutOfRangeException(
                    context,
                    $"Motor State integer value must be in {minimum}..{maximum}");
            }
        }
'''
if source.count(old) != 1:
    raise SystemExit(f"integer helper anchor count={source.count(old)}")
source = source.replace(old, new, 1)
shim.write_text(source, encoding="utf-8")

raw_ranges = repo / "tests" / "test_reference_renderer_raw_numeric_ranges.py"
ranges_source = raw_ranges.read_text(encoding="utf-8")
old_ranges = '''def test_integer_range_guard_remains_separate_from_raw_number_range_guard() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert 'RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L)' in source
    assert 'RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L)' in source
    integer = source[source.index("private static void RequireIntegerRangeToken") :]
    assert "long.TryParse(" in integer
    assert "value < minimum || value > maximum" in integer
'''
new_ranges = '''def test_integer_range_guard_remains_separate_from_raw_number_range_guard() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert 'RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L)' in source
    assert 'RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L)' in source
    integer = source[source.index("private static void RequireIntegerToken") : source.index("private static void RequireExactFields")]
    assert "RequireNumericToken(raw, context);" in integer
    assert "IsIntegralJsonNumber(raw)" in integer
    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in integer
    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in integer
    assert "long.TryParse(\\n                    raw," not in integer
    assert "float.Parse" not in integer
    assert "double.Parse" not in integer
    assert "decimal.Parse" not in integer
'''
if ranges_source.count(old_ranges) != 1:
    raise SystemExit(f"raw ranges test anchor count={ranges_source.count(old_ranges)}")
ranges_source = ranges_source.replace(old_ranges, new_ranges, 1)
raw_ranges.write_text(ranges_source, encoding="utf-8")

whitespace = repo / "tests" / "test_reference_renderer_json_whitespace_guard.py"
whitespace_source = whitespace.read_text(encoding="utf-8")
old_ws = '''    assert "Regex.IsMatch(raw, \\\"^(?:\\\" + JsonIntegerPattern" in numeric
    assert "raw.Trim()," not in numeric
'''
new_ws = '''    assert "JsonIntegerPattern" not in numeric
    assert "RequireNumericToken(raw, context);" in numeric
    assert "raw.Trim()," not in numeric
'''
if whitespace_source.count(old_ws) != 1:
    raise SystemExit(f"whitespace integer anchor count={whitespace_source.count(old_ws)}")
whitespace_source = whitespace_source.replace(old_ws, new_ws, 1)
old_guard = '''def test_raw_integer_ranges_are_checked_before_unity_int_coercion() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[source.index("private static void RequireIntegerRangeToken") :]
    assert "long.TryParse(" in helper
    assert "NumberStyles.AllowLeadingSign" in helper
    assert "CultureInfo.InvariantCulture" in helper
    assert "value < minimum || value > maximum" in helper
    assert "ArgumentOutOfRangeException" in helper
'''
new_guard = '''def test_raw_integer_ranges_are_checked_before_unity_int_coercion() -> None:
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
    assert "ArgumentOutOfRangeException" in helper
'''
if whitespace_source.count(old_guard) != 1:
    raise SystemExit(f"raw integer guard test anchor count={whitespace_source.count(old_guard)}")
whitespace_source = whitespace_source.replace(old_guard, new_guard, 1)
whitespace.write_text(whitespace_source, encoding="utf-8")

parity = repo / "tests" / "test_reference_renderer_integer_number_schema_parity.py"
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
    for parser in ("float.Parse", "double.Parse", "decimal.Parse", "float.TryParse", "double.TryParse", "decimal.TryParse"):
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
