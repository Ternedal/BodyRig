from pathlib import Path

repo = Path(__file__).resolve().parents[1]
shim = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
source = shim.read_text(encoding="utf-8")

old = '''            if (!root.TryGetValue("version", out var rawVersion) ||
                !Regex.IsMatch(rawVersion, "^[123]$", RegexOptions.CultureInvariant))
            {
                throw new ArgumentException("Motor State requires integer version 1, 2, or 3");
            }
            var version = int.Parse(rawVersion);
'''
new = '''            var version = RequireMotorStateVersion(root);
'''
if source.count(old) != 1:
    raise SystemExit(f"version validation anchor count={source.count(old)}")
source = source.replace(old, new, 1)

anchor = '''        private static string[] RootFieldsForVersion(int version)
'''
helper = '''        private static int RequireMotorStateVersion(Dictionary<string, string> root)
        {
            if (!root.TryGetValue("version", out var rawVersion))
            {
                throw new ArgumentException("Motor State requires numeric version 1, 2, or 3");
            }
            RequireNumericToken(rawVersion, "version");
            if (CompareJsonNumberToInteger(rawVersion, 1L) == 0) return 1;
            if (CompareJsonNumberToInteger(rawVersion, 2L) == 0) return 2;
            if (CompareJsonNumberToInteger(rawVersion, 3L) == 0) return 3;
            throw new ArgumentException("Motor State requires numeric version 1, 2, or 3");
        }

'''
if source.count(anchor) != 1:
    raise SystemExit(f"root fields helper anchor count={source.count(anchor)}")
source = source.replace(anchor, helper + anchor, 1)
shim.write_text(source, encoding="utf-8")

test = repo / "tests" / "test_reference_renderer_version_schema_parity.py"
if test.exists():
    raise SystemExit("version schema parity regression already exists")
test.write_text('''from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]


def test_renderer_version_guard_uses_schema_numeric_const_semantics() -> None:
    constants = [json.loads(path.read_text(encoding="utf-8"))["properties"]["version"]["const"] for path in SCHEMAS]
    assert constants == [1, 2, 3]

    source = SHIM.read_text(encoding="utf-8")
    validate = source[
        source.index("private static void ValidateMotorStatePresenceAndTypes") :
        source.index("private static int RequireMotorStateVersion")
    ]
    assert "var version = RequireMotorStateVersion(root);" in validate
    assert 'Regex.IsMatch(rawVersion, "^[123]$"' not in validate
    assert "int.Parse(rawVersion)" not in validate

    helper = source[
        source.index("private static int RequireMotorStateVersion") :
        source.index("private static string[] RootFieldsForVersion")
    ]
    assert 'RequireNumericToken(rawVersion, "version");' in helper
    for version in constants:
        assert f"CompareJsonNumberToInteger(rawVersion, {version}L) == 0" in helper
        assert f"return {version};" in helper
    assert "numeric version 1, 2, or 3" in helper


def test_version_guard_reuses_exact_decimal_number_comparator() -> None:
    source = SHIM.read_text(encoding="utf-8")
    comparator = source[
        source.index("private static int CompareJsonNumberToInteger") :
        source.index("private static int CompareDecimalMagnitude")
    ]
    assert "double.Parse" not in comparator
    assert "float.Parse" not in comparator
    assert "decimal.Parse" not in comparator
    assert "explicitExponent" in comparator
    assert "fractionalDigits" in comparator
    assert "CompareDecimalMagnitude" in comparator

    numeric = source[
        source.index("private static void RequireNumericToken") :
        source.index("private static void RequireNumericRangeToken")
    ]
    assert "JsonNumberPattern" in numeric
    assert "RegexOptions.CultureInvariant" in numeric
''', encoding="utf-8")
