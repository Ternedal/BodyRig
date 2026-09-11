from pathlib import Path

shim = Path("reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs")
source = shim.read_text(encoding="utf-8")

old_duration = '''            if (root.TryGetValue("duration_ms", out var raw))
            {
                RequireIntegerToken(raw, "duration_ms");
            }
'''
new_duration = '''            if (root.TryGetValue("duration_ms", out var raw))
            {
                RequireIntegerToken(raw, 0L, 120000L, "duration_ms");
            }
'''
if source.count(old_duration) != 1:
    raise SystemExit(f"duration anchor count={source.count(old_duration)}")
source = source.replace(old_duration, new_duration, 1)

old_speech = '''            var fields = ParseObjectMembers(raw, "speech");
            RequireAllowedAndRequiredFields(fields, SpeechAllowedFields, SpeechRequiredFields, "speech");
            RequireStringMember(fields, "state", "speech");
            RequireIntegerMember(fields, "elapsed_ms", "speech");
            if (fields.ContainsKey("viseme")) RequireStringMember(fields, "viseme", "speech");
            if (fields.ContainsKey("amplitude")) RequireNumericMember(fields, "amplitude", "speech");
'''
new_speech = '''            var fields = ParseObjectMembers(raw, "speech");
            RequireAllowedAndRequiredFields(fields, SpeechAllowedFields, SpeechRequiredFields, "speech");
            var state = RequireStringMember(fields, "state", "speech");
            if (state != "start" && state != "update" && state != "stop")
            {
                throw new ArgumentException("Motor State speech state must be start, update, or stop");
            }
            RequireIntegerMember(fields, "elapsed_ms", 0L, 3600000L, "speech");
            if (fields.ContainsKey("viseme"))
            {
                var viseme = RequireStringMember(fields, "viseme", "speech");
                if (viseme.Length < 1 || viseme.Length > 32 ||
                    !Regex.IsMatch(viseme, "^[A-Za-z0-9._-]+$", RegexOptions.CultureInvariant))
                {
                    throw new ArgumentException("Motor State speech viseme violates schema constraints");
                }
            }
            if (fields.ContainsKey("amplitude")) RequireNumericMember(fields, "amplitude", "speech");
'''
if source.count(old_speech) != 1:
    raise SystemExit(f"speech anchor count={source.count(old_speech)}")
source = source.replace(old_speech, new_speech, 1)

old_member = '''        private static void RequireIntegerMember(
            Dictionary<string, string> members,
            string field,
            string context)
        {
            if (!members.TryGetValue(field, out var raw))
            {
                throw new ArgumentException($"Motor State {context} is missing required field: {field}");
            }
            RequireIntegerToken(raw, context + "." + field);
        }
'''
new_member = '''        private static void RequireIntegerMember(
            Dictionary<string, string> members,
            string field,
            long minimum,
            long maximum,
            string context)
        {
            if (!members.TryGetValue(field, out var raw))
            {
                throw new ArgumentException($"Motor State {context} is missing required field: {field}");
            }
            RequireIntegerToken(raw, minimum, maximum, context + "." + field);
        }
'''
if source.count(old_member) != 1:
    raise SystemExit(f"integer member anchor count={source.count(old_member)}")
source = source.replace(old_member, new_member, 1)

old_token = '''        private static void RequireIntegerToken(string raw, string context)
        {
            if (!Regex.IsMatch(raw.Trim(), "^(?:" + JsonIntegerPattern + ")$", RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} requires an integer JSON token");
            }
        }
'''
new_token = '''        private static void RequireIntegerToken(
            string raw,
            long minimum,
            long maximum,
            string context)
        {
            var token = raw.Trim();
            if (!Regex.IsMatch(token, "^(?:" + JsonIntegerPattern + ")$", RegexOptions.CultureInvariant) ||
                !long.TryParse(token, out var value) ||
                value < minimum ||
                value > maximum)
            {
                throw new ArgumentException(
                    $"Motor State {context} requires an integer JSON token in range [{minimum}, {maximum}]");
            }
        }
'''
if source.count(old_token) != 1:
    raise SystemExit(f"integer token anchor count={source.count(old_token)}")
source = source.replace(old_token, new_token, 1)

shim.write_text(source, encoding="utf-8")

test = Path("tests/test_reference_renderer_json_schema_value_guard.py")
test.write_text('''from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
SCHEMA = REPO / "contracts" / "bodyrig-motor-state-v3.schema.json"


def test_integer_ranges_are_pinned_to_schema_before_unity_deserialization() -> None:
    source = SHIM.read_text(encoding="utf-8")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    duration = schema["properties"]["duration_ms"]
    speech = schema["properties"]["speech"]["properties"]

    assert f'RequireIntegerToken(raw, {duration["minimum"]}L, {duration["maximum"]}L, "duration_ms")' in source
    assert f'RequireIntegerMember(fields, "elapsed_ms", {speech["elapsed_ms"]["minimum"]}L, {speech["elapsed_ms"]["maximum"]}L, "speech")' in source
    assert "long.TryParse(token, out var value)" in source
    assert "value < minimum" in source
    assert "value > maximum" in source


def test_speech_state_and_viseme_constraints_match_schema() -> None:
    source = SHIM.read_text(encoding="utf-8")
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    speech = schema["properties"]["speech"]["properties"]
    block = source[source.index("private static void ValidateSpeech") : source.index("private static void ValidatePosture")]

    for state in speech["state"]["enum"]:
        assert f'state != "{state}"' in block

    viseme = speech["viseme"]
    assert f"viseme.Length > {viseme['maxLength']}" in block
    assert f'"{viseme["pattern"]}"' in block
    assert "viseme.Length < 1" in block
    assert "RegexOptions.CultureInvariant" in block
''', encoding="utf-8")
