from pathlib import Path

GUARD = Path("reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs")
TEST = Path("tests/test_reference_renderer_json_utility_guard.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"expected one marker, found {count}: {old[:100]!r}")
    return text.replace(old, new, 1)


def patch_guard() -> None:
    text = GUARD.read_text(encoding="utf-8")

    root_arrays = '''        private static readonly string[] RootV1Fields =
        {
            "type",
            "version",
            "body_id",
            "utterance_id",
            "motion",
            "expression",
            "gesture",
            "gaze",
            "posture",
            "duration_ms",
            "speech",
        };

        private static readonly string[] RootV2Fields =
        {
            "type",
            "version",
            "body_id",
            "utterance_id",
            "motion",
            "expression",
            "gesture",
            "gaze",
            "posture",
            "duration_ms",
            "speech",
            "embodiment",
        };

        private static readonly string[] RootV3Fields =
        {
            "type",
            "version",
            "body_id",
            "utterance_id",
            "motion",
            "expression",
            "gesture",
            "gaze",
            "posture",
            "locomotion",
            "duration_ms",
            "speech",
            "embodiment",
        };

'''
    text = replace_once(
        text,
        '        private static readonly string[] MotionFields =\n',
        root_arrays + '        private static readonly string[] MotionFields =\n',
    )

    old = '''            var version = int.Parse(rawVersion.Trim());

            RequireStringMember(root, "body_id", "root");
            RequireStringMember(root, "utterance_id", "root");
            ValidateRequiredExactObject(root, "motion", MotionFields, "motion", Array.Empty<string>());
            ValidateOptionalExactObject(root, "expression", ExpressionFields, "expression", new[] { "emotion" });
            ValidateOptionalExactObject(root, "gesture", GestureFields, "gesture", new[] { "id" });
            ValidateOptionalExactObject(root, "gaze", GazeFields, "gaze", new[] { "target" });
'''
    new = '''            var version = int.Parse(rawVersion.Trim());

            RequireAllowedFields(root, RootFieldsForVersion(version), "root");
            RequireConstrainedStringMember(
                root, "body_id", "root", 1, 160, "^[a-z0-9æøå_-]+$");
            RequireConstrainedStringMember(
                root, "utterance_id", "root", 1, 160, "^[A-Za-z0-9._:-]+$");
            ValidateRequiredExactObject(root, "motion", MotionFields, "motion", Array.Empty<string>());
            ValidateOptionalExactObject(root, "expression", ExpressionFields, "expression", new[] { "emotion" });
            ValidateOptionalConstrainedString(
                root, "expression", "emotion", "expression", 1, 64, "^[a-z0-9_-]+$");
            ValidateOptionalExactObject(root, "gesture", GestureFields, "gesture", new[] { "id" });
            ValidateOptionalConstrainedString(
                root, "gesture", "id", "gesture", 1, 80, "^[a-z0-9_-]+$");
            ValidateOptionalExactObject(root, "gaze", GazeFields, "gaze", new[] { "target" });
            ValidateOptionalConstrainedString(
                root, "gaze", "target", "gaze", 1, 127, null);
'''
    text = replace_once(text, old, new)

    marker = '''        private static void ValidateRequiredExactObject(
'''
    helpers = '''        private static string[] RootFieldsForVersion(int version)
        {
            switch (version)
            {
                case 1: return RootV1Fields;
                case 2: return RootV2Fields;
                case 3: return RootV3Fields;
                default: throw new ArgumentOutOfRangeException(nameof(version));
            }
        }

        private static void ValidateOptionalConstrainedString(
            Dictionary<string, string> parent,
            string propertyName,
            string field,
            string context,
            int minimumLength,
            int maximumLength,
            string pattern)
        {
            if (!parent.TryGetValue(propertyName, out var raw))
            {
                return;
            }
            var members = ParseObjectMembers(raw, context);
            RequireConstrainedStringMember(
                members, field, context, minimumLength, maximumLength, pattern);
        }

'''
    text = replace_once(text, marker, helpers + marker)

    text = replace_once(
        text,
        '            if (fields.ContainsKey("viseme")) RequireStringMember(fields, "viseme", "speech");\n',
        '''            if (fields.ContainsKey("viseme"))
            {
                RequireConstrainedStringMember(
                    fields, "viseme", "speech", 1, 32, "^[A-Za-z0-9._-]+$");
            }
''',
    )

    text = replace_once(
        text,
        '            var id = RequireStringMember(fields, "id", "posture");\n',
        '''            var id = RequireConstrainedStringMember(
                fields, "id", "posture", 1, 80, "^[a-z0-9_-]+$");
''',
    )

    marker = '''        private static void RequireNumericMember(
'''
    constrained_helper = '''        private static string RequireConstrainedStringMember(
            Dictionary<string, string> members,
            string field,
            string context,
            int minimumLength,
            int maximumLength,
            string pattern)
        {
            var value = RequireStringMember(members, field, context);
            ValidateDecodedString(value, context + "." + field, minimumLength, maximumLength, pattern);
            return value;
        }

        private static void ValidateDecodedString(
            string value,
            string context,
            int minimumLength,
            int maximumLength,
            string pattern)
        {
            var length = UnicodeScalarLength(value, context);
            if (length < minimumLength || length > maximumLength)
            {
                throw new ArgumentException(
                    $"Motor State {context} length must be {minimumLength}..{maximumLength}");
            }
            if (pattern != null && !Regex.IsMatch(value, pattern, RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} does not match canonical pattern");
            }
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
    text = replace_once(text, marker, constrained_helper + marker)
    GUARD.write_text(text, encoding="utf-8")


def patch_tests() -> None:
    text = TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''    assert 'RequireStringMember(root, "body_id", "root")' in validate
    assert 'RequireStringMember(root, "utterance_id", "root")' in validate
''',
        '''    assert 'root, "body_id", "root", 1, 160, "^[a-z0-9æøå_-]+$"' in validate
    assert 'root, "utterance_id", "root", 1, 160, "^[A-Za-z0-9._:-]+$"' in validate
''',
    )
    text = replace_once(
        text,
        '''    assert 'RequireStringMember(fields, "viseme", "speech")' in speech
''',
        '''    assert 'fields, "viseme", "speech", 1, 32, "^[A-Za-z0-9._-]+$"' in speech
''',
    )

    addition = r'''


def _root_properties(path: Path) -> set[str]:
    return set(_contract(path)["properties"])


def test_root_allowlists_match_canonical_version_properties() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert _array_fields(source, "RootV1Fields") == _root_properties(MOTOR_V1)
    assert _array_fields(source, "RootV2Fields") == _root_properties(MOTOR_V2)
    assert _array_fields(source, "RootV3Fields") == _root_properties(MOTOR_V3)
    validate = source[
        source.index("private static void ValidateMotorStatePresenceAndTypes") :
        source.index("private static void ValidateRequiredExactObject")
    ]
    assert 'RequireAllowedFields(root, RootFieldsForVersion(version), "root");' in validate


def test_decoded_string_constraints_match_canonical_shared_schema() -> None:
    source = SHIM.read_text(encoding="utf-8")
    schemas = [_contract(path) for path in (MOTOR_V1, MOTOR_V2, MOTOR_V3)]

    for field in ("body_id", "utterance_id"):
        expected = schemas[0]["properties"][field]
        assert all(item["properties"][field] == expected for item in schemas)
        assert f'root, "{field}", "root", {expected["minLength"]}, {expected["maxLength"]}, "{expected["pattern"]}"' in source

    shared = (
        ("expression", "emotion", 64, "^[a-z0-9_-]+$"),
        ("gesture", "id", 80, "^[a-z0-9_-]+$"),
        ("gaze", "target", 127, None),
    )
    for object_name, field, maximum, pattern in shared:
        expected = schemas[0]["properties"][object_name]["properties"][field]
        assert all(item["properties"][object_name]["properties"][field] == expected for item in schemas)
        assert expected["minLength"] == 1
        assert expected["maxLength"] == maximum
        if pattern is None:
            assert "pattern" not in expected
            needle = f'root, "{object_name}", "{field}", "{object_name}", 1, {maximum}, null'
        else:
            assert expected["pattern"] == pattern
            needle = f'root, "{object_name}", "{field}", "{object_name}", 1, {maximum}, "{pattern}"'
        assert needle in source

    viseme = schemas[0]["properties"]["speech"]["properties"]["viseme"]
    assert all(item["properties"]["speech"]["properties"]["viseme"] == viseme for item in schemas)
    assert f'fields, "viseme", "speech", {viseme["minLength"]}, {viseme["maxLength"]}, "{viseme["pattern"]}"' in source


def test_posture_id_constraint_matches_generic_schema_variants() -> None:
    source = SHIM.read_text(encoding="utf-8")
    v1 = _contract(MOTOR_V1)["properties"]["posture"]["properties"]["id"]
    v2 = _contract(MOTOR_V2)["properties"]["posture"]["properties"]["id"]
    generic_v3 = next(
        item for item in _contract(MOTOR_V3)["properties"]["posture"]["oneOf"]
        if "const" not in item["properties"]["id"]
    )["properties"]["id"]
    assert v1 == v2 == generic_v3
    assert f'fields, "id", "posture", {v1["minLength"]}, {v1["maxLength"]}, "{v1["pattern"]}"' in source
    assert 'source != "modelrig-bodyprint-v1"' in source


def test_string_constraints_run_on_decoded_tokens_and_count_unicode_scalars() -> None:
    source = SHIM.read_text(encoding="utf-8")
    constrained = source[
        source.index("private static string RequireConstrainedStringMember") :
        source.index("private static void RequireNumericMember")
    ]
    assert "var value = RequireStringMember" in constrained
    assert "ValidateDecodedString(value" in constrained
    assert "UnicodeScalarLength(value, context)" in constrained
    assert "char.IsHighSurrogate" in constrained
    assert "char.IsLowSurrogate" in constrained
    assert "Regex.IsMatch(value, pattern, RegexOptions.CultureInvariant)" in constrained


def test_gaze_keeps_arbitrary_legal_string_content_except_schema_length() -> None:
    source = SHIM.read_text(encoding="utf-8")
    validate = source[
        source.index("private static void ValidateMotorStatePresenceAndTypes") :
        source.index("private static void ValidateRequiredExactObject")
    ]
    assert 'root, "gaze", "target", "gaze", 1, 127, null' in validate
    assert "ParseObjectMembers" in source
    assert "ReadJsonString" in source
    assert "FlatObjectPattern" not in source


def test_root_duplicate_decoded_keys_remain_fail_closed() -> None:
    source = SHIM.read_text(encoding="utf-8")
    parser = source[
        source.index("private static Dictionary<string, string> ParseObjectMembers") :
        source.index("private static void SkipJsonValue")
    ]
    assert "ReadJsonString(json, ref index" in parser
    assert "members.TryAdd(key, rawValue)" in parser
    assert "contains duplicate field" in parser
'''
    if "test_root_allowlists_match_canonical_version_properties" in text:
        raise RuntimeError("tests already patched")
    TEST.write_text(text.rstrip() + addition.rstrip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    patch_guard()
    patch_tests()
