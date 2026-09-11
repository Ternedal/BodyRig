from pathlib import Path

repo = Path(__file__).resolve().parents[2]
shim = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
whitespace_test = repo / "tests" / "test_reference_renderer_json_whitespace_guard.py"
parity_test = repo / "tests" / "test_reference_renderer_version_schema_parity.py"

source = shim.read_text(encoding="utf-8")
old = '''            if (!root.TryGetValue("version", out var rawVersion) ||
                !Regex.IsMatch(rawVersion, "^[123]$", RegexOptions.CultureInvariant))
            {
                throw new ArgumentException("Motor State requires integer version 1, 2, or 3");
            }
            var version = int.Parse(rawVersion);
'''
new = '''            if (!root.TryGetValue("version", out var rawVersion))
            {
                throw new ArgumentException("Motor State requires numeric version 1, 2, or 3");
            }
            RequireNumericToken(rawVersion, "version");
            int version;
            if (CompareJsonNumberToInteger(rawVersion, 1L) == 0)
            {
                version = 1;
            }
            else if (CompareJsonNumberToInteger(rawVersion, 2L) == 0)
            {
                version = 2;
            }
            else if (CompareJsonNumberToInteger(rawVersion, 3L) == 0)
            {
                version = 3;
            }
            else
            {
                throw new ArgumentException("Motor State requires numeric version 1, 2, or 3");
            }
'''
if source.count(old) != 1:
    raise SystemExit(f"version validation anchor mismatch: {source.count(old)}")
source = source.replace(old, new)
if 'Regex.IsMatch(rawVersion, "^[123]$"' in source or "int.Parse(rawVersion)" in source:
    raise SystemExit("legacy lexical version validation survived")
shim.write_text(source, encoding="utf-8")

ws = whitespace_test.read_text(encoding="utf-8")
old_ws = '''    assert 'Regex.IsMatch(rawVersion, "^[123]$"' in validate
    assert "rawVersion.Trim()" not in validate
    assert "int.Parse(rawVersion)" in validate
'''
new_ws = '''    assert 'RequireNumericToken(rawVersion, "version");' in validate
    assert "CompareJsonNumberToInteger(rawVersion, 1L) == 0" in validate
    assert "CompareJsonNumberToInteger(rawVersion, 2L) == 0" in validate
    assert "CompareJsonNumberToInteger(rawVersion, 3L) == 0" in validate
    assert 'Regex.IsMatch(rawVersion, "^[123]$"' not in validate
    assert "rawVersion.Trim()" not in validate
    assert "int.Parse(rawVersion)" not in validate
'''
if ws.count(old_ws) != 1:
    raise SystemExit("whitespace version test anchor mismatch")
whitespace_test.write_text(ws.replace(old_ws, new_ws), encoding="utf-8")

if parity_test.exists():
    raise SystemExit("version schema parity test already exists")
parity_test.write_text('''from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]


def _validation_block() -> str:
    source = SHIM.read_text(encoding="utf-8")
    return source[
        source.index("private static void ValidateMotorStatePresenceAndTypes") :
        source.index("private static string[] RootFieldsForVersion")
    ]


def test_version_schema_consts_are_numeric_1_2_3() -> None:
    consts = [
        json.loads(path.read_text(encoding="utf-8"))["properties"]["version"]["const"]
        for path in SCHEMAS
    ]
    assert consts == [1, 2, 3]
    assert all(type(value) is int for value in consts)


def test_renderer_matches_version_by_exact_json_decimal_value() -> None:
    validate = _validation_block()
    assert 'RequireNumericToken(rawVersion, "version");' in validate
    for version in (1, 2, 3):
        assert f"CompareJsonNumberToInteger(rawVersion, {version}L) == 0" in validate
        assert f"version = {version};" in validate
    assert 'Regex.IsMatch(rawVersion, "^[123]$"' not in validate
    assert "int.Parse(rawVersion)" not in validate
    assert "float.Parse" not in validate
    assert "double.Parse" not in validate
    assert "decimal.Parse" not in validate


def test_schema_equivalent_version_spellings_are_value_equal() -> None:
    equivalents = {
        1: ["1", "1.0", "1e0", "10e-1"],
        2: ["2", "2.0", "2e0", "20e-1"],
        3: ["3", "3.0", "3e0", "30e-1"],
    }
    for version, spellings in equivalents.items():
        expected = Decimal(version)
        for spelling in spellings:
            # These are valid JSON number tokens and JSON Schema numeric const
            # equality is value-based rather than lexical.
            assert isinstance(json.loads(spelling), (int, float))
            assert Decimal(spelling) == expected


def test_version_path_reuses_canonical_number_grammar_and_exact_comparator() -> None:
    source = SHIM.read_text(encoding="utf-8")
    validate = _validation_block()
    numeric = source[
        source.index("private static void RequireNumericToken") :
        source.index("private static void RequireIntegerToken")
    ]
    assert 'RequireNumericToken(rawVersion, "version");' in validate
    assert "JsonNumberPattern" in numeric
    assert "CompareJsonNumberToInteger" in numeric
    assert "CompareDecimalMagnitude" in numeric
    assert "float.TryParse" not in numeric
    assert "double.TryParse" not in numeric
    # JSON's leading-zero form remains invalid before decimal comparison.
    try:
        json.loads("01")
    except json.JSONDecodeError:
        pass
    else:
        raise AssertionError("01 must not be accepted as a JSON number token")
''', encoding="utf-8")
