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
        '''            RequireAllowedAndRequiredFields(fields, SpeechAllowedFields, SpeechRequiredFields, "speech");
            RequireStringMember(fields, "state", "speech");
            RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);
''',
        '''            RequireAllowedAndRequiredFields(fields, SpeechAllowedFields, SpeechRequiredFields, "speech");
            var state = RequireStringMember(fields, "state", "speech");
            if (state != "start" && state != "update" && state != "stop")
            {
                throw new ArgumentException("Motor State speech state must be start, update, or stop");
            }
            RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);
''',
    )

    text = replace_once(
        text,
        '''            if (pattern != null && !Regex.IsMatch(value, pattern, RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} does not match canonical pattern");
            }
        }

        private static int UnicodeScalarLength(string value, string context)
''',
        '''            if (pattern != null && !MatchesCanonicalWholeStringPattern(value, pattern))
            {
                throw new ArgumentException($"Motor State {context} does not match canonical pattern");
            }
        }

        private static bool MatchesCanonicalWholeStringPattern(string value, string pattern)
        {
            if (pattern.Length < 2 || pattern[0] != '^' || pattern[pattern.Length - 1] != '$')
            {
                throw new ArgumentException("Motor State canonical string pattern must be whole-string anchored");
            }
            var body = pattern.Substring(1, pattern.Length - 2);
            return Regex.IsMatch(
                value,
                "\\A(?:" + body + ")\\z",
                RegexOptions.CultureInvariant);
        }

        private static int UnicodeScalarLength(string value, string context)
''',
    )

    GUARD.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    assert 'RequireStringMember(fields, "state", "speech")' in speech
''',
        '''    assert 'var state = RequireStringMember(fields, "state", "speech")' in speech
    assert 'state != "start" && state != "update" && state != "stop"' in speech
''',
    )
    text = replace_once(
        text,
        '''    assert "Regex.IsMatch(value, pattern, RegexOptions.CultureInvariant)" in constrained
''',
        '''    assert "MatchesCanonicalWholeStringPattern(value, pattern)" in constrained
    assert '"\\\\A(?:" + body + ")\\\\z"' in constrained
    assert "pattern[0] != '^'" in constrained
    assert "pattern[pattern.Length - 1] != '$'" in constrained
''',
    )

    addition = r'''


def test_schema_patterns_use_absolute_dotnet_end_anchor() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[
        source.index("private static bool MatchesCanonicalWholeStringPattern") :
        source.index("private static int UnicodeScalarLength")
    ]
    assert '"\\A(?:" + body + ")\\z"' in helper
    assert "RegexOptions.CultureInvariant" in helper
    assert "Regex.IsMatch(value, pattern" not in helper
    assert "pattern[0] != '^'" in helper
    assert "pattern[pattern.Length - 1] != '$'" in helper


def test_speech_state_enum_fails_closed_before_unity_assignment() -> None:
    source = SHIM.read_text(encoding="utf-8")
    speech = source[
        source.index("private static void ValidateSpeech") :
        source.index("private static void ValidatePosture")
    ]
    assert 'var state = RequireStringMember(fields, "state", "speech")' in speech
    assert 'state != "start" && state != "update" && state != "stop"' in speech
    assert "speech state must be start, update, or stop" in speech
'''
    if "test_schema_patterns_use_absolute_dotnet_end_anchor" in text:
        raise RuntimeError("review refinement tests already present")
    TEST.write_text(text.rstrip() + addition.rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    patch_guard()
    patch_tests()
