from pathlib import Path

repo = Path(__file__).resolve().parents[2]
shim_path = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
test_path = repo / "tests" / "test_reference_renderer_json_utility_guard.py"

shim = shim_path.read_text(encoding="utf-8")
old = '''        private static string RequireConstrainedStringMember(
            Dictionary<string, string> members,
            string field,
            string context,
            int minimumLength,
            int maximumLength,
            string pattern)
        {
            var value = RequireStringMember(members, field, context);
            if (value.Length < minimumLength || value.Length > maximumLength)
            {
                throw new ArgumentOutOfRangeException(
                    context + "." + field,
                    $"Motor State string length must be in {minimumLength}..{maximumLength}");
            }
            if (pattern != null && !Regex.IsMatch(value, pattern, RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context}.{field} violates the canonical string pattern");
            }
            return value;
        }
'''
new = '''        private static string RequireConstrainedStringMember(
            Dictionary<string, string> members,
            string field,
            string context,
            int minimumLength,
            int maximumLength,
            string pattern)
        {
            var value = RequireStringMember(members, field, context);
            var scalarLength = UnicodeScalarLength(value, context + "." + field);
            if (scalarLength < minimumLength || scalarLength > maximumLength)
            {
                throw new ArgumentOutOfRangeException(
                    context + "." + field,
                    $"Motor State string length must be in {minimumLength}..{maximumLength} Unicode scalars");
            }
            if (pattern != null && !Regex.IsMatch(value, pattern, RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context}.{field} violates the canonical string pattern");
            }
            return value;
        }

        private static int UnicodeScalarLength(string value, string context)
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
assert old in shim
assert "private static int UnicodeScalarLength(" not in shim
shim = shim.replace(old, new, 1)
shim_path.write_text(shim, encoding="utf-8")

test = test_path.read_text(encoding="utf-8")
old_assert = '    assert "value.Length < minimumLength || value.Length > maximumLength" in helper\n'
new_assert = '''    assert 'var scalarLength = UnicodeScalarLength(value, context + "." + field);' in helper
    assert "scalarLength < minimumLength || scalarLength > maximumLength" in helper
    assert "char.IsHighSurrogate" in helper
    assert "char.IsLowSurrogate" in helper
    assert "contains an unpaired surrogate" in helper
'''
assert old_assert in test
test = test.replace(old_assert, new_assert, 1)

extra = '''\n\ndef test_schema_string_length_uses_unicode_scalars_not_utf16_code_units() -> None:\n    source = SHIM.read_text(encoding="utf-8")\n    block = source[\n        source.index("private static string RequireConstrainedStringMember") :\n        source.index("private static void RequireNumericMember")\n    ]\n    assert 'var scalarLength = UnicodeScalarLength(value, context + "." + field);' in block\n    assert "value.Length < minimumLength" not in block\n    assert "char.IsHighSurrogate(current)" in block\n    assert "char.IsLowSurrogate(value[index + 1])" in block\n    assert "char.IsLowSurrogate(current)" in block\n    assert "index++;" in block\n    assert "count++;" in block\n'''
assert "test_schema_string_length_uses_unicode_scalars_not_utf16_code_units" not in test
test += extra

test_path.write_text(test, encoding="utf-8")
