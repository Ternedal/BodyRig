from pathlib import Path

GUARD = Path("reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs")
TEST = Path("tests/test_reference_renderer_json_utility_guard.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one marker, found {count}: {old[:140]!r}")
    return text.replace(old, new, 1)


def patch_guard() -> None:
    text = GUARD.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''            var scalarLength = CountUnicodeScalars(value, context + "." + field);
            if (scalarLength < minimumLength || scalarLength > maximumLength)
            {
                throw new ArgumentOutOfRangeException(
                    context + "." + field,
                    $"Motor State string length must be in {minimumLength}..{maximumLength} Unicode scalars");
            }
''',
        '''            var codePointLength = CountJsonCodePoints(value);
            if (codePointLength < minimumLength || codePointLength > maximumLength)
            {
                throw new ArgumentOutOfRangeException(
                    context + "." + field,
                    $"Motor State string length must be in {minimumLength}..{maximumLength} JSON code points");
            }
''',
    )
    old = '''        private static int CountUnicodeScalars(string value, string context)
        {
            var count = 0;
            for (var index = 0; index < value.Length; index++)
            {
                var current = value[index];
                if (char.IsHighSurrogate(current))
                {
                    if (index + 1 >= value.Length || !char.IsLowSurrogate(value[index + 1]))
                    {
                        throw new ArgumentException($"Motor State {context} contains an unpaired high surrogate");
                    }
                    index++;
                    count++;
                    continue;
                }
                if (char.IsLowSurrogate(current))
                {
                    throw new ArgumentException($"Motor State {context} contains an unpaired low surrogate");
                }
                count++;
            }
            return count;
        }
'''
    new = '''        private static int CountJsonCodePoints(string value)
        {
            var count = 0;
            for (var index = 0; index < value.Length; index++)
            {
                if (char.IsHighSurrogate(value[index]) &&
                    index + 1 < value.Length &&
                    char.IsLowSurrogate(value[index + 1]))
                {
                    index++;
                }
                count++;
            }
            return count;
        }
'''
    text = replace_once(text, old, new)
    GUARD.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    assert 'CountUnicodeScalars(value, context + "." + field)' in helper
    assert "scalarLength < minimumLength || scalarLength > maximumLength" in helper
''',
        '''    assert "CountJsonCodePoints(value)" in helper
    assert "codePointLength < minimumLength || codePointLength > maximumLength" in helper
''',
    )
    old = '''def test_schema_string_length_counts_unicode_scalars_and_rejects_unpaired_surrogates() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[source.index("private static int CountUnicodeScalars") : source.index("private static void RequireNumericMember")]
    assert "for (var index = 0; index < value.Length; index++)" in helper
    assert "char.IsHighSurrogate(current)" in helper
    assert "char.IsLowSurrogate(value[index + 1])" in helper
    assert "index++;" in helper
    assert "count++;" in helper
    assert "unpaired high surrogate" in helper
    assert "char.IsLowSurrogate(current)" in helper
    assert "unpaired low surrogate" in helper
    constrained = source[source.index("private static string RequireConstrainedStringMember") : source.index("private static int CountUnicodeScalars")]
    assert "var scalarLength = CountUnicodeScalars(value" in constrained
    assert "Unicode scalars" in constrained
'''
    new = '''def test_schema_string_length_counts_json_code_points_including_lone_surrogates() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[source.index("private static int CountJsonCodePoints") : source.index("private static void RequireNumericMember")]
    assert "for (var index = 0; index < value.Length; index++)" in helper
    assert "char.IsHighSurrogate(value[index])" in helper
    assert "index + 1 < value.Length" in helper
    assert "char.IsLowSurrogate(value[index + 1])" in helper
    assert "index++;" in helper
    assert "count++;" in helper
    assert "throw" not in helper
    assert "unpaired" not in helper
    constrained = source[source.index("private static string RequireConstrainedStringMember") : source.index("private static int CountJsonCodePoints")]
    assert "var codePointLength = CountJsonCodePoints(value);" in constrained
    assert "JSON code points" in constrained


def test_json_code_point_counter_combines_valid_pairs_without_rejecting_lone_surrogates() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[source.index("private static int CountJsonCodePoints") : source.index("private static void RequireNumericMember")]
    assert "char.IsHighSurrogate(value[index])" in helper
    assert "char.IsLowSurrogate(value[index + 1])" in helper
    assert "index++;" in helper
    assert "count++;" in helper
    assert "throw" not in helper
    # RFC 8259 grammar permits escaped lone surrogate code points; the length
    # boundary must count them rather than invent a scalar-only restriction.
    assert "IsLowSurrogate(value[index])" not in helper
'''
    text = replace_once(text, old, new)
    TEST.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_guard()
    patch_tests()
