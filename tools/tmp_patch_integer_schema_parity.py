from pathlib import Path

shim = Path("reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs")
source = shim.read_text(encoding="utf-8")

old_const = '        private const string JsonIntegerPattern = "-?(?:0|[1-9][0-9]*)";\n'
if source.count(old_const) != 1:
    raise SystemExit(f"JsonIntegerPattern anchor count={source.count(old_const)}")
source = source.replace(old_const, "", 1)

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
new = '''        private static bool IsIntegralJsonNumber(string raw)
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

            var hasNonZeroDigit = false;
            var trailingZeroDigits = 0;
            for (var index = cursor; index < mantissaEnd; index++)
            {
                var digit = raw[index];
                if (digit == '.') continue;
                if (digit == '0')
                {
                    if (hasNonZeroDigit) trailingZeroDigits++;
                    continue;
                }
                hasNonZeroDigit = true;
                trailingZeroDigits = 0;
            }

            if (!hasNonZeroDigit) return true;
            if (exponent10 >= 0L) return true;
            if (exponent10 == long.MinValue) return false;
            return -exponent10 <= trailingZeroDigits;
        }

        private static void RequireIntegerToken(string raw, string context)
        {
            RequireNumericToken(raw, context);
            if (!IsIntegralJsonNumber(raw))
            {
                throw new ArgumentException($"Motor State {context} requires an integer-valued JSON number");
            }
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

whitespace = Path("tests/test_reference_renderer_json_whitespace_guard.py")
text = whitespace.read_text(encoding="utf-8")
old_assert = '    assert "Regex.IsMatch(raw, \\\"^(?:\\\" + JsonIntegerPattern" in numeric\n'
new_assert = '    assert "RequireNumericToken(raw, context);" in numeric\n    assert "JsonIntegerPattern" not in numeric\n'
if text.count(old_assert) != 1:
    raise SystemExit(f"whitespace assertion anchor count={text.count(old_assert)}")
whitespace.write_text(text.replace(old_assert, new_assert, 1), encoding="utf-8")

regression = Path("tests/test_reference_renderer_integer_schema_parity.py")
regression.write_text('''from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]


def _integer_contracts(path: Path) -> tuple[dict, dict]:
    schema = json.loads(path.read_text(encoding="utf-8"))
    return (
        dict(schema["properties"]["duration_ms"]),
        dict(schema["properties"]["speech"]["properties"]["elapsed_ms"]),
    )


def test_integer_contract_is_shared_across_motor_state_versions() -> None:
    contracts = [_integer_contracts(path) for path in SCHEMAS]
    assert all(contract == contracts[0] for contract in contracts[1:])
    duration, elapsed = contracts[0]
    assert duration == {"type": "integer", "minimum": 0, "maximum": 120000}
    assert elapsed == {"type": "integer", "minimum": 0, "maximum": 3600000}


def test_raw_integer_guard_uses_value_semantics_not_lexical_integer_spelling() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert "JsonIntegerPattern" not in source

    helper = source[
        source.index("private static bool IsIntegralJsonNumber") :
        source.index("private static void RequireIntegerToken")
    ]
    assert "fractionalDigits" in helper
    assert "explicitExponent" in helper
    assert "SaturatingSubtract(explicitExponent, fractionalDigits)" in helper
    assert "trailingZeroDigits" in helper
    assert "if (!hasNonZeroDigit) return true;" in helper
    assert "if (exponent10 >= 0L) return true;" in helper
    assert "if (exponent10 == long.MinValue) return false;" in helper
    assert "return -exponent10 <= trailingZeroDigits;" in helper

    token = source[
        source.index("private static void RequireIntegerToken") :
        source.index("private static void RequireIntegerRangeToken")
    ]
    assert "RequireNumericToken(raw, context);" in token
    assert "IsIntegralJsonNumber(raw)" in token
    assert "Regex.IsMatch" not in token


def test_integer_ranges_use_existing_exact_decimal_comparator() -> None:
    source = SHIM.read_text(encoding="utf-8")
    range_guard = source[
        source.index("private static void RequireIntegerRangeToken") :
        source.index("private static void RequireExactFields")
    ]
    assert "RequireIntegerToken(raw, context);" in range_guard
    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in range_guard
    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in range_guard
    assert "long.TryParse(\n                    raw," not in range_guard


def test_integer_fields_route_through_value_semantic_range_guard() -> None:
    source = SHIM.read_text(encoding="utf-8")
    duration = source[
        source.index("private static void ValidateDuration") :
        source.index("private static void ValidateSpeech")
    ]
    speech = source[
        source.index("private static void ValidateSpeech") :
        source.index("private static void ValidatePosture")
    ]
    assert 'RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L);' in duration
    assert 'RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);' in speech
''', encoding="utf-8")
