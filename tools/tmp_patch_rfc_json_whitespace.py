from pathlib import Path

shim = Path("reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs")
source = shim.read_text(encoding="utf-8")

replacements = [
    (
        '!Regex.IsMatch(rawVersion.Trim(), "^[123]$", RegexOptions.CultureInvariant)',
        '!Regex.IsMatch(TrimJsonWhitespace(rawVersion), "^[123]$", RegexOptions.CultureInvariant)',
    ),
    (
        'var version = int.Parse(rawVersion.Trim());',
        'var version = int.Parse(TrimJsonWhitespace(rawVersion), CultureInfo.InvariantCulture);',
    ),
    (
        '!char.IsWhiteSpace(json[index]) &&',
        '!IsJsonWhitespace(json[index]) &&',
    ),
    (
        'while (index < json.Length && char.IsWhiteSpace(json[index])) index++;',
        'while (index < json.Length && IsJsonWhitespace(json[index])) index++;',
    ),
    (
        'Regex.IsMatch(raw.Trim(), "^(?:" + JsonNumberPattern + ")$", RegexOptions.CultureInvariant)',
        'Regex.IsMatch(TrimJsonWhitespace(raw), "^(?:" + JsonNumberPattern + ")$", RegexOptions.CultureInvariant)',
    ),
    (
        'var token = raw.Trim();',
        'var token = TrimJsonWhitespace(raw);',
    ),
    (
        'Regex.IsMatch(raw.Trim(), "^(?:" + JsonIntegerPattern + ")$", RegexOptions.CultureInvariant)',
        'Regex.IsMatch(TrimJsonWhitespace(raw), "^(?:" + JsonIntegerPattern + ")$", RegexOptions.CultureInvariant)',
    ),
    (
        'raw.Trim(),\n                    NumberStyles.AllowLeadingSign,',
        'TrimJsonWhitespace(raw),\n                    NumberStyles.AllowLeadingSign,',
    ),
]

for old, new in replacements:
    count = source.count(old)
    if old.startswith('while (index < json.Length && char.IsWhiteSpace'):
        if count != 2:
            raise SystemExit(f"expected 2 whitespace loops, got {count}")
        source = source.replace(old, new)
        continue
    if count != 1:
        raise SystemExit(f"anchor count={count} for {old!r}")
    source = source.replace(old, new, 1)

anchor = '''        private static void SkipWhitespace(string json, ref int index)
        {
            while (index < json.Length && IsJsonWhitespace(json[index])) index++;
        }
'''
helper = '''        private static bool IsJsonWhitespace(char value)
        {
            return value == ' ' || value == '\\t' || value == '\\n' || value == '\\r';
        }

        private static string TrimJsonWhitespace(string value)
        {
            var start = 0;
            while (start < value.Length && IsJsonWhitespace(value[start])) start++;
            var end = value.Length;
            while (end > start && IsJsonWhitespace(value[end - 1])) end--;
            return start == 0 && end == value.Length
                ? value
                : value.Substring(start, end - start);
        }

'''
if source.count(anchor) != 1:
    raise SystemExit(f"SkipWhitespace anchor count={source.count(anchor)}")
source = source.replace(anchor, helper + anchor, 1)
shim.write_text(source, encoding="utf-8")

test = Path("tests/test_reference_renderer_json_whitespace_guard.py")
test.write_text('''from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"


def test_motor_state_raw_guard_uses_only_rfc8259_json_whitespace() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[
        source.index("private static bool IsJsonWhitespace") :
        source.index("private static string ReadJsonString")
    ]

    assert "return value == ' ' || value == '\\\\t' || value == '\\\\n' || value == '\\\\r';" in helper
    assert "char.IsWhiteSpace" not in source
    assert "while (index < json.Length && IsJsonWhitespace(json[index])) index++;" in helper
    assert "!IsJsonWhitespace(json[index])" in source


def test_motor_state_tokens_do_not_broad_trim_unicode_whitespace() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert "private static string TrimJsonWhitespace" in source
    assert "rawVersion.Trim()" not in source
    assert "raw.Trim()" not in source
    assert 'Regex.IsMatch(TrimJsonWhitespace(rawVersion), "^[123]$"' in source
    assert "var version = int.Parse(TrimJsonWhitespace(rawVersion), CultureInfo.InvariantCulture);" in source
    assert 'Regex.IsMatch(TrimJsonWhitespace(raw), "^(?:" + JsonNumberPattern + ")$"' in source
    assert 'Regex.IsMatch(TrimJsonWhitespace(raw), "^(?:" + JsonIntegerPattern + ")$"' in source
    assert "var token = TrimJsonWhitespace(raw);" in source
    assert "TrimJsonWhitespace(raw),\\n                    NumberStyles.AllowLeadingSign," in source


def test_json_whitespace_set_excludes_unicode_whitespace_that_dotnet_accepts() -> None:
    # RFC 8259 ws is exactly SP, HTAB, LF and CR. Keep a concrete regression set
    # for common Unicode whitespace chars accepted by .NET Char.IsWhiteSpace.
    json_ws = {" ", "\\t", "\\n", "\\r"}
    for non_json_ws in ("\\u00a0", "\\u0085", "\\u2028", "\\u2029", "\\u3000"):
        assert non_json_ws not in json_ws
''', encoding="utf-8")
