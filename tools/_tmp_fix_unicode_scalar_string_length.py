from pathlib import Path

GUARD = Path("reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs")
TEST = Path("tests/test_reference_renderer_json_utility_guard.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one marker, found {count}: {old[:120]!r}")
    return text.replace(old, new, 1)


def patch_guard() -> None:
    text = GUARD.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''            var value = RequireStringMember(members, field, context);
            if (value.Length < minimumLength || value.Length > maximumLength)
            {
                throw new ArgumentOutOfRangeException(
                    context + "." + field,
                    $"Motor State string length must be in {minimumLength}..{maximumLength}");
            }
''',
        '''            var value = RequireStringMember(members, field, context);
            var scalarLength = UnicodeScalarLength(value, context + "." + field);
            if (scalarLength < minimumLength || scalarLength > maximumLength)
            {
                throw new ArgumentOutOfRangeException(
                    context + "." + field,
                    $"Motor State string length must be in {minimumLength}..{maximumLength}");
            }
''',
    )

    marker = '''        private static void RequireNumericMember(
'''
    helper = '''        private static int UnicodeScalarLength(string value, string context)
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
    text = replace_once(text, marker, helper + marker)
    GUARD.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    assert "value.Length < minimumLength || value.Length > maximumLength" in helper
''',
        '''    assert 'var scalarLength = UnicodeScalarLength(value, context + "." + field);' in helper
    assert "scalarLength < minimumLength || scalarLength > maximumLength" in helper
''',
    )
    addition = r'''


def test_canonical_string_length_counts_unicode_scalars_not_utf16_units() -> None:
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
    if "test_canonical_string_length_counts_unicode_scalars_not_utf16_units" in text:
        raise RuntimeError("Unicode scalar regression test already present")
    TEST.write_text(text.rstrip() + addition.rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    patch_guard()
    patch_tests()
