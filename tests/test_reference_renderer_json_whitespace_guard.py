from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"


def _slice(source: str, start: str, end: str) -> str:
    return source[source.index(start) : source.index(end)]


def test_raw_scanner_uses_only_rfc8259_json_whitespace() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = _slice(
        source,
        "private static bool IsJsonWhitespace",
        "private static void SkipWhitespace",
    )
    assert "return value == ' ' || value == '\\t' || value == '\\n' || value == '\\r';" in helper
    assert "char.IsWhiteSpace(value) && !IsJsonWhitespace(value)" in helper

    skip_value = _slice(
        source,
        "private static void SkipJsonValue",
        "private static void SkipComposite",
    )
    assert "!IsJsonWhitespace(json[index])" in skip_value
    assert "char.IsWhiteSpace(json[index])" not in skip_value

    whitespace = _slice(
        source,
        "private static void SkipWhitespace",
        "private static bool TryParseStringToken",
    )
    assert "while (index < json.Length && IsJsonWhitespace(json[index])) index++;" in whitespace
    assert "char.IsWhiteSpace(json[index])" not in whitespace


def test_non_rfc_unicode_whitespace_cannot_bypass_root_probe() -> None:
    source = SHIM.read_text(encoding="utf-8")
    validate = _slice(
        source,
        "private static void ValidateMotorStatePresenceAndTypes",
        "private static string[] RootFieldsForVersion",
    )
    assert "string.IsNullOrEmpty(json)" in validate
    assert "string.IsNullOrWhiteSpace(json)" not in validate
    assert "SkipWhitespace(json, ref probeIndex);" in validate
    assert "IsNonJsonWhitespace(json[probeIndex])" in validate
    assert "Motor State JSON contains non-RFC whitespace" in validate


def test_raw_version_and_number_tokens_are_not_broadly_trimmed() -> None:
    source = SHIM.read_text(encoding="utf-8")
    validate = _slice(
        source,
        "private static void ValidateMotorStatePresenceAndTypes",
        "private static string[] RootFieldsForVersion",
    )
    assert "var version = RequireMotorStateVersion(root);" in validate
    assert "rawVersion.Trim()" not in validate
    assert 'Regex.IsMatch(rawVersion, "^[123]$"' not in validate
    assert "int.Parse(rawVersion)" not in validate
    assert 'RequireNumericToken(rawVersion, "version");' in validate

    numeric = _slice(
        source,
        "private static void RequireNumericToken",
        "private static void RequireExactFields",
    )
    assert "Regex.IsMatch(raw," in numeric
    assert "var token = raw;" in numeric
    assert "Regex.IsMatch(raw.Trim()" not in numeric
    assert "var token = raw.Trim()" not in numeric
    assert "Regex.IsMatch(raw, \"^(?:\" + JsonIntegerPattern" in numeric
    assert "raw.Trim()," not in numeric
    # Decimal digit normalization is intentional and unrelated to JSON whitespace.
    assert "TrimStart('0')" in numeric


def test_unicode_whitespace_remains_legal_inside_json_strings() -> None:
    source = SHIM.read_text(encoding="utf-8")
    reader = _slice(
        source,
        "private static string ReadJsonString",
        "private static int HexValue",
    )
    assert "current < 0x20" in reader
    assert "result.Append(current);" in reader
    assert "IsJsonWhitespace" not in reader
    assert "IsNonJsonWhitespace" not in reader
