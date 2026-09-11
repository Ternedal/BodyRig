from pathlib import Path

repo = Path(__file__).resolve().parents[2]
shim_path = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
test_path = repo / "tests" / "test_reference_renderer_json_utility_guard.py"

shim = shim_path.read_text(encoding="utf-8")

marker = "        public static T FromJson<T>(string json)\n"
assert marker in shim
root_defs = '''        private const string BodyIdPattern = "^[a-z0-9æøå_-]+$";
        private const string UtteranceIdPattern = "^[A-Za-z0-9._:-]+$";

        private static readonly string[] RootV1Fields =
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
            "duration_ms",
            "speech",
            "embodiment",
            "locomotion",
        };

'''
assert "RootV1Fields" not in shim
shim = shim.replace(marker, root_defs + marker, 1)

old_validate = '''            var version = int.Parse(rawVersion.Trim());

            RequireStringMember(root, "body_id", "root");
            RequireStringMember(root, "utterance_id", "root");
'''
new_validate = '''            var version = int.Parse(rawVersion.Trim());

            RequireAllowedFields(
                root,
                version == 1 ? RootV1Fields : version == 2 ? RootV2Fields : RootV3Fields,
                "root");
            RequireConstrainedStringMember(
                root, "body_id", "root", 1, 160, BodyIdPattern);
            RequireConstrainedStringMember(
                root, "utterance_id", "root", 1, 160, UtteranceIdPattern);
'''
assert old_validate in shim
shim = shim.replace(old_validate, new_validate, 1)

helper_marker = '''        private static void RequireNumericMember(
'''
assert helper_marker in shim
constraint_helper = '''        private static string RequireConstrainedStringMember(
            Dictionary<string, string> members,
            string field,
            string context,
            int minimumLength,
            int maximumLength,
            string pattern)
        {
            var value = RequireStringMember(members, field, context);
            if (value.Length < minimumLength ||
                value.Length > maximumLength ||
                !Regex.IsMatch(value, pattern, RegexOptions.CultureInvariant))
            {
                throw new ArgumentException(
                    $"Motor State {context} has invalid string field: {field}");
            }
            return value;
        }

'''
assert "private static string RequireConstrainedStringMember(" not in shim
shim = shim.replace(helper_marker, constraint_helper + helper_marker, 1)
shim_path.write_text(shim, encoding="utf-8")

test = test_path.read_text(encoding="utf-8")

contracts_marker = '''    contracts = [_contract(path) for path in (MOTOR_V1, MOTOR_V2, MOTOR_V3)]
'''
contracts_insert = '''    contracts = [_contract(path) for path in (MOTOR_V1, MOTOR_V2, MOTOR_V3)]
    for contract, array_name in zip(contracts, ("RootV1Fields", "RootV2Fields", "RootV3Fields"), strict=True):
        assert contract["additionalProperties"] is False
        assert _array_fields(source, array_name) == set(contract["properties"])
'''
assert contracts_marker in test
assert "RootV1Fields" not in test
test = test.replace(contracts_marker, contracts_insert, 1)

raw_marker = '''    assert 'root.TryGetValue("version", out var rawVersion)' in validate
    assert 'ValidateRequiredExactObject(root, "motion"' in validate
'''
raw_insert = '''    assert 'root.TryGetValue("version", out var rawVersion)' in validate
    assert "version == 1 ? RootV1Fields : version == 2 ? RootV2Fields : RootV3Fields" in validate
    assert 'RequireConstrainedStringMember(\\n                root, "body_id", "root", 1, 160, BodyIdPattern)' in validate
    assert 'RequireConstrainedStringMember(\\n                root, "utterance_id", "root", 1, 160, UtteranceIdPattern)' in validate
    assert 'ValidateRequiredExactObject(root, "motion"' in validate
'''
assert raw_marker in test
test = test.replace(raw_marker, raw_insert, 1)

new_test = r'''

def test_root_identifier_constraints_follow_all_motor_schemas() -> None:
    source = SHIM.read_text(encoding="utf-8")
    contracts = [_contract(path) for path in (MOTOR_V1, MOTOR_V2, MOTOR_V3)]
    body_specs = [contract["properties"]["body_id"] for contract in contracts]
    utterance_specs = [contract["properties"]["utterance_id"] for contract in contracts]
    assert body_specs[1:] == body_specs[:-1]
    assert utterance_specs[1:] == utterance_specs[:-1]
    body = body_specs[0]
    utterance = utterance_specs[0]
    assert body == {
        "type": "string",
        "minLength": 1,
        "maxLength": 160,
        "pattern": "^[a-z0-9æøå_-]+$",
    }
    assert utterance == {
        "type": "string",
        "minLength": 1,
        "maxLength": 160,
        "pattern": "^[A-Za-z0-9._:-]+$",
    }
    assert f'private const string BodyIdPattern = "{body["pattern"]}";' in source
    assert f'private const string UtteranceIdPattern = "{utterance["pattern"]}";' in source
    helper = source[source.index("private static string RequireConstrainedStringMember") :]
    assert "value.Length < minimumLength" in helper
    assert "value.Length > maximumLength" in helper
    assert "Regex.IsMatch(value, pattern, RegexOptions.CultureInvariant)" in helper
'''
assert "test_root_identifier_constraints_follow_all_motor_schemas" not in test
test += new_test

test_path.write_text(test, encoding="utf-8")
