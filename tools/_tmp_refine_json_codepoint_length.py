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
        '''            var scalarLength = UnicodeScalarLength(value, context + "." + field);
''',
        '''            var scalarLength = JsonCodePointLength(value);
''',
    )
    old = '''        private static int UnicodeScalarLength(string value, string context)
        {
            var count = 0;
            for (var index = 0; index < value.Length; index++)
            {
                var current = value[index];
                if (char.IsHighSurrogate(current))
                {
                    if (index + 1 >= value.Length || !char.IsLowSurrogate(value[index + 1]))
                    {
                        throw new ArgumentException($"Motor State {context} contains an unpaired surrogate");
                    }
                    index++;
                }
                else if (char.IsLowSurrogate(current))
                {
                    throw new ArgumentException($"Motor State {context} contains an unpaired surrogate");
                }
                count++;
            }
            return count;
        }
'''
    new = '''        private static int JsonCodePointLength(string value)
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
        '''    assert 'var scalarLength = UnicodeScalarLength(value, context + "." + field);' in helper
    assert "scalarLength < minimumLength || scalarLength > maximumLength" in helper
''',
        '''    assert "var scalarLength = JsonCodePointLength(value);" in helper
    assert "scalarLength < minimumLength || scalarLength > maximumLength" in helper
''',
    )
    old = '''def test_canonical_string_length_counts_unicode_scalars_not_utf16_units() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[
        source.index("private static string RequireConstrainedStringMember") :
        source.index("private static void RequireNumericMember")
    ]
    assert 'var scalarLength = UnicodeScalarLength(value, context + "." + field);' in helper
    assert "value.Length < minimumLength" not in helper
    assert "char.IsHighSurrogate(current)" in helper
    assert "char.IsLowSurrogate(value[index + 1])" in helper
    assert "else if (char.IsLowSurrogate(current))" in helper
    assert "index++;" in helper
    assert "count++;" in helper
    assert "contains an unpaired surrogate" in helper
    gaze = _contract(MOTOR_V3)["properties"]["gaze"]["properties"]["target"]
    assert gaze["minLength"] == 1
    assert gaze["maxLength"] == 127
    assert "pattern" not in gaze
'''
    new = '''def test_canonical_string_length_counts_json_code_points_not_utf16_units() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[
        source.index("private static string RequireConstrainedStringMember") :
        source.index("private static void RequireNumericMember")
    ]
    assert "var scalarLength = JsonCodePointLength(value);" in helper
    assert "value.Length < minimumLength" not in helper
    assert "char.IsHighSurrogate(value[index])" in helper
    assert "char.IsLowSurrogate(value[index + 1])" in helper
    assert "index++;" in helper
    assert "count++;" in helper
    assert "unpaired surrogate" not in helper
    gaze = _contract(MOTOR_V3)["properties"]["gaze"]["properties"]["target"]
    assert gaze["minLength"] == 1
    assert gaze["maxLength"] == 127
    assert "pattern" not in gaze


def test_json_code_point_length_combines_pairs_but_counts_lone_surrogates() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[
        source.index("private static int JsonCodePointLength") :
        source.index("private static void RequireNumericMember")
    ]
    assert "index + 1 < value.Length" in helper
    assert "char.IsHighSurrogate(value[index])" in helper
    assert "char.IsLowSurrogate(value[index + 1])" in helper
    assert "index++;" in helper
    assert "count++;" in helper
    assert "throw" not in helper
'''
    text = replace_once(text, old, new)
    TEST.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    patch_guard()
    patch_tests()
