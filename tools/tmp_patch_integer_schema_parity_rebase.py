from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTILITY = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
DRIVER = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
GUARD = ROOT / "tests" / "test_reference_renderer_json_utility_guard.py"
WHITESPACE = ROOT / "tests" / "test_reference_renderer_json_whitespace_guard.py"
RANGES = ROOT / "tests" / "test_reference_renderer_raw_numeric_ranges.py"
PARITY = ROOT / "tests" / "test_reference_renderer_integer_schema_parity.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    UTILITY,
    '        private const string JsonIntegerPattern = "-?(?:0|[1-9][0-9]*)";\n',
    '',
)
replace_once(
    UTILITY,
    '''        private static void RequireIntegerToken(string raw, string context)\n        {\n            if (!Regex.IsMatch(raw, "^(?:" + JsonIntegerPattern + ")$", RegexOptions.CultureInvariant))\n            {\n                throw new ArgumentException($"Motor State {context} requires an integer JSON token");\n            }\n        }\n\n        private static void RequireIntegerRangeToken(\n            string raw,\n            string context,\n            long minimum,\n            long maximum)\n        {\n            RequireIntegerToken(raw, context);\n            if (!long.TryParse(\n                    raw,\n                    NumberStyles.AllowLeadingSign,\n                    CultureInfo.InvariantCulture,\n                    out var value) ||\n                value < minimum || value > maximum)\n            {\n                throw new ArgumentOutOfRangeException(\n                    context,\n                    $"Motor State integer value must be in {minimum}..{maximum}");\n            }\n        }''',
    '''        private static bool IsIntegralJsonNumber(string raw)\n        {\n            var cursor = raw[0] == '-' ? 1 : 0;\n            var exponentIndex = raw.IndexOf('e', cursor);\n            if (exponentIndex < 0)\n            {\n                exponentIndex = raw.IndexOf('E', cursor);\n            }\n            var mantissaEnd = exponentIndex >= 0 ? exponentIndex : raw.Length;\n            var dotIndex = raw.IndexOf('.', cursor, mantissaEnd - cursor);\n            var fractionalDigits = dotIndex >= 0 ? mantissaEnd - dotIndex - 1 : 0;\n\n            long explicitExponent = 0L;\n            if (exponentIndex >= 0)\n            {\n                var exponentToken = raw.Substring(exponentIndex + 1);\n                if (!long.TryParse(\n                        exponentToken,\n                        NumberStyles.AllowLeadingSign,\n                        CultureInfo.InvariantCulture,\n                        out explicitExponent))\n                {\n                    explicitExponent = exponentToken[0] == '-' ? long.MinValue : long.MaxValue;\n                }\n            }\n            var exponent10 = SaturatingSubtract(explicitExponent, fractionalDigits);\n\n            var hasNonZeroDigit = false;\n            var trailingZeroDigits = 0;\n            for (var index = cursor; index < mantissaEnd; index++)\n            {\n                var digit = raw[index];\n                if (digit == '.') continue;\n                if (digit == '0')\n                {\n                    if (hasNonZeroDigit) trailingZeroDigits++;\n                    continue;\n                }\n                hasNonZeroDigit = true;\n                trailingZeroDigits = 0;\n            }\n\n            if (!hasNonZeroDigit) return true;\n            if (exponent10 >= 0L) return true;\n            if (exponent10 == long.MinValue) return false;\n            return -exponent10 <= trailingZeroDigits;\n        }\n\n        private static void RequireIntegerToken(string raw, string context)\n        {\n            RequireNumericToken(raw, context);\n            if (!IsIntegralJsonNumber(raw))\n            {\n                throw new ArgumentException($"Motor State {context} requires an integer-valued JSON number");\n            }\n        }\n\n        private static void RequireIntegerRangeToken(\n            string raw,\n            string context,\n            long minimum,\n            long maximum)\n        {\n            RequireIntegerToken(raw, context);\n            if (CompareJsonNumberToInteger(raw, minimum) < 0 ||\n                CompareJsonNumberToInteger(raw, maximum) > 0)\n            {\n                throw new ArgumentOutOfRangeException(\n                    context,\n                    $"Motor State integer value must be in {minimum}..{maximum}");\n            }\n        }''',
)

replace_once(DRIVER, '            public int elapsed_ms;', '            public float elapsed_ms;')
replace_once(DRIVER, '            public int duration_ms;', '            public float duration_ms;')

replace_once(
    GUARD,
    '''    assert "long.TryParse(" in helper\n    assert "NumberStyles.AllowLeadingSign" in helper\n    assert "CultureInfo.InvariantCulture" in helper\n    assert "value < minimum || value > maximum" in helper''',
    '''    assert "RequireIntegerToken(raw, context);" in helper\n    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in helper\n    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in helper\n    assert "long.TryParse(" not in helper''',
)
replace_once(
    WHITESPACE,
    '    assert "Regex.IsMatch(raw, \\\"^(?:\\\" + JsonIntegerPattern" in numeric\n',
    '    assert "RequireNumericToken(raw, context);" in numeric\n    assert "JsonIntegerPattern" not in numeric\n',
)
replace_once(
    RANGES,
    '''    assert "long.TryParse(" in integer\n    assert "value < minimum || value > maximum" in integer''',
    '''    assert "RequireIntegerToken(raw, context);" in integer\n    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in integer\n    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in integer\n    assert "long.TryParse(" not in integer''',
)

PARITY.write_text(
    '''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\n\nREPO = Path(__file__).resolve().parents[1]\nSHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"\nDRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"\nSCHEMAS = [\n    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",\n    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",\n    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",\n]\n\n\ndef _integer_contracts(path: Path) -> tuple[dict, dict]:\n    schema = json.loads(path.read_text(encoding="utf-8"))\n    return (\n        dict(schema["properties"]["duration_ms"]),\n        dict(schema["properties"]["speech"]["properties"]["elapsed_ms"]),\n    )\n\n\ndef test_integer_contract_is_shared_across_motor_state_versions() -> None:\n    contracts = [_integer_contracts(path) for path in SCHEMAS]\n    assert all(contract == contracts[0] for contract in contracts[1:])\n    duration, elapsed = contracts[0]\n    assert duration == {"type": "integer", "minimum": 0, "maximum": 120000}\n    assert elapsed == {"type": "integer", "minimum": 0, "maximum": 3600000}\n\n\ndef test_raw_integer_guard_uses_value_semantics_not_lexical_integer_spelling() -> None:\n    source = SHIM.read_text(encoding="utf-8")\n    assert "JsonIntegerPattern" not in source\n\n    helper = source[\n        source.index("private static bool IsIntegralJsonNumber") :\n        source.index("private static void RequireIntegerToken")\n    ]\n    assert "fractionalDigits" in helper\n    assert "explicitExponent" in helper\n    assert "SaturatingSubtract(explicitExponent, fractionalDigits)" in helper\n    assert "trailingZeroDigits" in helper\n    assert "if (!hasNonZeroDigit) return true;" in helper\n    assert "if (exponent10 >= 0L) return true;" in helper\n    assert "if (exponent10 == long.MinValue) return false;" in helper\n    assert "return -exponent10 <= trailingZeroDigits;" in helper\n\n    token = source[\n        source.index("private static void RequireIntegerToken") :\n        source.index("private static void RequireIntegerRangeToken")\n    ]\n    assert "RequireNumericToken(raw, context);" in token\n    assert "IsIntegralJsonNumber(raw)" in token\n    assert "Regex.IsMatch" not in token\n\n\ndef test_integer_ranges_use_existing_exact_decimal_comparator() -> None:\n    source = SHIM.read_text(encoding="utf-8")\n    range_guard = source[\n        source.index("private static void RequireIntegerRangeToken") :\n        source.index("private static void RequireExactFields")\n    ]\n    assert "RequireIntegerToken(raw, context);" in range_guard\n    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in range_guard\n    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in range_guard\n    assert "long.TryParse(" not in range_guard\n\n\ndef test_integer_fields_route_through_value_semantic_range_guard() -> None:\n    source = SHIM.read_text(encoding="utf-8")\n    duration = source[\n        source.index("private static void ValidateDuration") :\n        source.index("private static void ValidateSpeech")\n    ]\n    speech = source[\n        source.index("private static void ValidateSpeech") :\n        source.index("private static void ValidatePosture")\n    ]\n    assert 'RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L);' in duration\n    assert 'RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);' in speech\n\n\ndef test_unity_wire_uses_exact_float_transport_for_bounded_integer_fields() -> None:\n    duration, elapsed = _integer_contracts(SCHEMAS[0])\n    assert duration["maximum"] < 2**24\n    assert elapsed["maximum"] < 2**24\n\n    source = DRIVER.read_text(encoding="utf-8")\n    assert "public float duration_ms;" in source\n    assert "public int duration_ms;" not in source\n    assert "public float elapsed_ms;" in source\n    assert "public int elapsed_ms;" not in source\n    assert 'ValidateRange(next.duration_ms, 0.0f, 120000.0f, "duration_ms")' in source\n    assert "next.speech.elapsed_ms < 0 || next.speech.elapsed_ms > 3600000" in source\n''',
    encoding="utf-8",
)
