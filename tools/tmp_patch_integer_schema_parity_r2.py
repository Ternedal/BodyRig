from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label} anchor count={count}")
    return text.replace(old, new, 1)


shim = Path("reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs")
source = shim.read_text(encoding="utf-8")
source = replace_once(
    source,
    '        private const string JsonIntegerPattern = "-?(?:0|[1-9][0-9]*)";\n',
    "",
    "JsonIntegerPattern",
)
old_helpers = '''        private static void RequireIntegerToken(string raw, string context)
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
new_helpers = '''        private static bool IsIntegralJsonNumber(string raw)
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
source = replace_once(source, old_helpers, new_helpers, "integer helpers")
shim.write_text(source, encoding="utf-8")

driver = Path("reference-renderer/Assets/BodyRig/BodyRigMotorDriver.cs")
text = driver.read_text(encoding="utf-8")
text = replace_once(text, "            public int elapsed_ms;\n", "            public float elapsed_ms;\n", "speech elapsed wire")
text = replace_once(text, "            public int duration_ms;\n", "            public float duration_ms;\n", "duration wire")
driver.write_text(text, encoding="utf-8")

path = Path("tests/test_reference_renderer_json_whitespace_guard.py")
text = path.read_text(encoding="utf-8")
text = replace_once(
    text,
    '    assert "Regex.IsMatch(raw, \\\"^(?:\\\" + JsonIntegerPattern" in numeric\n',
    '    assert "RequireNumericToken(raw, context);" in numeric\n    assert "JsonIntegerPattern" not in numeric\n',
    "whitespace lexical integer assertion",
)
path.write_text(text, encoding="utf-8")

path = Path("tests/test_reference_renderer_json_utility_guard.py")
text = path.read_text(encoding="utf-8")
anchor = '    assert "long.TryParse(" in helper\n'
replacement = (
    '    assert "RequireIntegerToken(raw, context);" in helper\n'
    '    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in helper\n'
    '    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in helper\n'
    '    assert "long.TryParse(" not in helper\n'
)
text = replace_once(text, anchor, replacement, "json utility lexical integer assertion")
for obsolete in (
    '    assert "NumberStyles.AllowLeadingSign" in helper\n',
    '    assert "CultureInfo.InvariantCulture" in helper\n',
    '    assert "value < minimum || value > maximum" in helper\n',
):
    text = replace_once(text, obsolete, "", "json utility obsolete integer assertion")
path.write_text(text, encoding="utf-8")

path = Path("tests/test_reference_renderer_raw_numeric_ranges.py")
text = path.read_text(encoding="utf-8")
anchor = '    assert "long.TryParse(" in integer\n'
replacement = (
    '    assert "RequireIntegerToken(raw, context);" in integer\n'
    '    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in integer\n'
    '    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in integer\n'
    '    assert "long.TryParse(" not in integer\n'
)
text = replace_once(text, anchor, replacement, "raw numeric lexical integer assertion")
text = replace_once(
    text,
    '    assert "value < minimum || value > maximum" in integer\n',
    "",
    "raw numeric obsolete integer assertion",
)
path.write_text(text, encoding="utf-8")

regression = Path("tests/test_reference_renderer_integer_schema_parity.py")
regression.write_text('''from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
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
    assert duration["maximum"] < 2**24
    assert elapsed["maximum"] < 2**24


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
    assert "long.TryParse(" not in range_guard


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


def test_private_unity_wire_uses_exact_float_transport_for_bounded_integer_fields() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    speech_state = source[
        source.index("private sealed class SpeechState") :
        source.index("private sealed class ObservedEmbodimentState")
    ]
    motor_state = source[
        source.index("private sealed class MotorState") :
        source.index("[SerializeField] private BodyRigAvatarLoader")
    ]
    assert "public float elapsed_ms;" in speech_state
    assert "public int elapsed_ms;" not in speech_state
    assert "public float duration_ms;" in motor_state
    assert "public int duration_ms;" not in motor_state
    # Preserve the version-authority follow-up this patch is based on.
    assert "public float version;" in motor_state

    apply = source[
        source.index("public void ApplyMotorJson") :
        source.index("private static void ValidatePosture")
    ]
    assert 'ValidateRange(next.duration_ms, 0.0f, 120000.0f, "duration_ms");' in apply
    assert "next.speech.elapsed_ms < 0 || next.speech.elapsed_ms > 3600000" in apply
''', encoding="utf-8")
