from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTILITY = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
DRIVER = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
GUARD = ROOT / "tests" / "test_reference_renderer_json_utility_guard.py"
VERSION = ROOT / "tests" / "test_reference_renderer_version_authority.py"
TRANSPORT = ROOT / "tests" / "test_reference_renderer_integer_transport_authority.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)


utility = UTILITY.read_text(encoding="utf-8")
utility = replace_once(
    utility,
    '''        internal static int ValidateMotorStateJson(string json)\n        {\n            ValidateMotorStatePresenceAndTypes(json, true, out var validatedVersion);\n            if (!validatedVersion.HasValue)\n            {\n                throw new ArgumentException("Motor State semantic version is required");\n            }\n            return validatedVersion.Value;\n        }\n''',
    '''        internal static int ValidateMotorStateJson(string json)\n        {\n            return ValidateMotorStateJson(json, out _, out _);\n        }\n\n        internal static int ValidateMotorStateJson(\n            string json,\n            out int? validatedDurationMs,\n            out int? validatedSpeechElapsedMs)\n        {\n            ValidateMotorStatePresenceAndTypes(\n                json,\n                true,\n                out var validatedVersion,\n                out validatedDurationMs,\n                out validatedSpeechElapsedMs);\n            if (!validatedVersion.HasValue)\n            {\n                throw new ArgumentException("Motor State semantic version is required");\n            }\n            return validatedVersion.Value;\n        }\n''',
    "dedicated validator",
)
utility = replace_once(
    utility,
    '''        private static void ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)\n        {\n            ValidateMotorStatePresenceAndTypes(json, requireMotorState, out _);\n        }\n\n        private static void ValidateMotorStatePresenceAndTypes(\n            string json,\n            bool requireMotorState,\n            out int? validatedVersion)\n        {\n            validatedVersion = null;\n''',
    '''        private static void ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)\n        {\n            ValidateMotorStatePresenceAndTypes(json, requireMotorState, out _, out _, out _);\n        }\n\n        private static void ValidateMotorStatePresenceAndTypes(\n            string json,\n            bool requireMotorState,\n            out int? validatedVersion,\n            out int? validatedDurationMs,\n            out int? validatedSpeechElapsedMs)\n        {\n            validatedVersion = null;\n            validatedDurationMs = null;\n            validatedSpeechElapsedMs = null;\n''',
    "raw validator outputs",
)
utility = replace_once(
    utility,
    '''            ValidateObjectNumericRange(root, "gaze", "strength", "gaze", 0L, 1L);\n            ValidateDuration(root);\n            ValidateSpeech(root);\n            ValidatePosture(root, version);\n''',
    '''            ValidateObjectNumericRange(root, "gaze", "strength", "gaze", 0L, 1L);\n            validatedDurationMs = ValidateDuration(root);\n            validatedSpeechElapsedMs = ValidateSpeech(root);\n            ValidatePosture(root, version);\n''',
    "validated integer assignments",
)
utility = replace_once(
    utility,
    '''        private static void ValidateDuration(Dictionary<string, string> root)\n        {\n            if (root.TryGetValue("duration_ms", out var raw))\n            {\n                RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L);\n            }\n        }\n\n        private static void ValidateSpeech(Dictionary<string, string> root)\n        {\n            if (!root.TryGetValue("speech", out var raw))\n            {\n                return;\n            }\n\n            var fields = ParseObjectMembers(raw, "speech");\n            RequireAllowedAndRequiredFields(fields, SpeechAllowedFields, SpeechRequiredFields, "speech");\n            var state = RequireStringMember(fields, "state", "speech");\n            if (state != "start" && state != "update" && state != "stop")\n            {\n                throw new ArgumentException("Motor State speech state must be start, update, or stop");\n            }\n            RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);\n            if (fields.ContainsKey("viseme"))\n            {\n                RequireConstrainedStringMember(fields, "viseme", "speech", 1, 32, VisemePattern);\n            }\n            if (fields.ContainsKey("amplitude"))\n            {\n                RequireNumericRangeMember(fields, "amplitude", "speech", 0L, 1L);\n            }\n        }\n''',
    '''        private static int? ValidateDuration(Dictionary<string, string> root)\n        {\n            if (!root.TryGetValue("duration_ms", out var raw))\n            {\n                return null;\n            }\n            return RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L);\n        }\n\n        private static int? ValidateSpeech(Dictionary<string, string> root)\n        {\n            if (!root.TryGetValue("speech", out var raw))\n            {\n                return null;\n            }\n\n            var fields = ParseObjectMembers(raw, "speech");\n            RequireAllowedAndRequiredFields(fields, SpeechAllowedFields, SpeechRequiredFields, "speech");\n            var state = RequireStringMember(fields, "state", "speech");\n            if (state != "start" && state != "update" && state != "stop")\n            {\n                throw new ArgumentException("Motor State speech state must be start, update, or stop");\n            }\n            var elapsedMs = RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);\n            if (fields.ContainsKey("viseme"))\n            {\n                RequireConstrainedStringMember(fields, "viseme", "speech", 1, 32, VisemePattern);\n            }\n            if (fields.ContainsKey("amplitude"))\n            {\n                RequireNumericRangeMember(fields, "amplitude", "speech", 0L, 1L);\n            }\n            return elapsedMs;\n        }\n''',
    "duration and speech canonical values",
)
utility = replace_once(
    utility,
    '''        private static void RequireIntegerRangeMember(\n            Dictionary<string, string> members,\n            string field,\n            string context,\n            long minimum,\n            long maximum)\n        {\n            if (!members.TryGetValue(field, out var raw))\n            {\n                throw new ArgumentException($"Motor State {context} is missing required field: {field}");\n            }\n            RequireIntegerRangeToken(raw, context + "." + field, minimum, maximum);\n        }\n''',
    '''        private static int RequireIntegerRangeMember(\n            Dictionary<string, string> members,\n            string field,\n            string context,\n            long minimum,\n            long maximum)\n        {\n            if (!members.TryGetValue(field, out var raw))\n            {\n                throw new ArgumentException($"Motor State {context} is missing required field: {field}");\n            }\n            return RequireIntegerRangeToken(raw, context + "." + field, minimum, maximum);\n        }\n''',
    "integer member return",
)
utility = replace_once(
    utility,
    '''        private static void RequireIntegerRangeToken(\n            string raw,\n            string context,\n            long minimum,\n            long maximum)\n        {\n            RequireIntegerToken(raw, context);\n            if (CompareJsonNumberToInteger(raw, minimum) < 0 ||\n                CompareJsonNumberToInteger(raw, maximum) > 0)\n            {\n                throw new ArgumentOutOfRangeException(\n                    context,\n                    $"Motor State integer value must be in {minimum}..{maximum}");\n            }\n        }\n''',
    '''        private static int RequireIntegerRangeToken(\n            string raw,\n            string context,\n            long minimum,\n            long maximum)\n        {\n            RequireIntegerToken(raw, context);\n            if (CompareJsonNumberToInteger(raw, minimum) < 0 ||\n                CompareJsonNumberToInteger(raw, maximum) > 0)\n            {\n                throw new ArgumentOutOfRangeException(\n                    context,\n                    $"Motor State integer value must be in {minimum}..{maximum}");\n            }\n            if (minimum < int.MinValue || maximum > int.MaxValue)\n            {\n                throw new InvalidOperationException("Motor State integer canonicalization requires Int32 bounds");\n            }\n\n            var low = (int)minimum;\n            var high = (int)maximum;\n            while (low <= high)\n            {\n                var midpoint = low + ((high - low) / 2);\n                var comparison = CompareJsonNumberToInteger(raw, midpoint);\n                if (comparison == 0) return midpoint;\n                if (comparison < 0) high = midpoint - 1;\n                else low = midpoint + 1;\n            }\n            throw new ArgumentException($"Motor State {context} integer value could not be canonicalized");\n        }\n''',
    "integer range canonicalization",
)
UTILITY.write_text(utility, encoding="utf-8")

driver = DRIVER.read_text(encoding="utf-8")
driver = replace_once(driver, "            public int elapsed_ms;\n", "            public int elapsed_ms { get; set; }\n", "speech elapsed wire field")
driver = replace_once(driver, "            public int duration_ms;\n", "            public int duration_ms { get; set; }\n", "duration wire field")
driver = replace_once(
    driver,
    "            var validatedVersion = JsonUtility.ValidateMotorStateJson(json);\n            var next = JsonUtility.FromJson<MotorState>(json);\n",
    "            var validatedVersion = JsonUtility.ValidateMotorStateJson(\n                json, out var validatedDurationMs, out var validatedSpeechElapsedMs);\n            var next = JsonUtility.FromJson<MotorState>(json);\n",
    "driver raw validator call",
)
driver = replace_once(
    driver,
    '''            next.version = validatedVersion;\n            if (string.IsNullOrWhiteSpace(next.body_id) || string.IsNullOrWhiteSpace(next.utterance_id) || next.motion == null)\n''',
    '''            next.version = validatedVersion;\n            next.duration_ms = validatedDurationMs ?? 0;\n            if (validatedSpeechElapsedMs.HasValue != (next.speech != null))\n            {\n                throw new ArgumentException("Motor State speech transport does not match raw validated presence", nameof(json));\n            }\n            if (next.speech != null)\n            {\n                next.speech.elapsed_ms = validatedSpeechElapsedMs.Value;\n            }\n            if (string.IsNullOrWhiteSpace(next.body_id) || string.IsNullOrWhiteSpace(next.utterance_id) || next.motion == null)\n''',
    "driver canonical assignment",
)
DRIVER.write_text(driver, encoding="utf-8")

guard = GUARD.read_text(encoding="utf-8")
guard = replace_once(
    guard,
    '    helper = source[source.index("private static void RequireIntegerRangeToken") :]\n',
    '    helper = source[source.index("private static int RequireIntegerRangeToken") :]\n',
    "guard helper signature",
)
guard = replace_once(
    guard,
    '''    assert "internal static int ValidateMotorStateJson(string json)" in shim\n    dedicated = shim[\n        shim.index("internal static int ValidateMotorStateJson") :\n        shim.index("public static T FromJson<T>")\n    ]\n    assert "ValidateMotorStatePresenceAndTypes(json, true, out var validatedVersion);" in dedicated\n    assert "return validatedVersion.Value;" in dedicated\n''',
    '''    assert "internal static int ValidateMotorStateJson(string json)" in shim\n    assert "out int? validatedDurationMs" in shim\n    assert "out int? validatedSpeechElapsedMs" in shim\n    dedicated = shim[\n        shim.index("internal static int ValidateMotorStateJson") :\n        shim.index("public static T FromJson<T>")\n    ]\n    assert "return ValidateMotorStateJson(json, out _, out _);" in dedicated\n    assert "out validatedDurationMs" in dedicated\n    assert "out validatedSpeechElapsedMs" in dedicated\n    assert "return validatedVersion.Value;" in dedicated\n''',
    "guard dedicated validator assertions",
)
guard = replace_once(
    guard,
    '''    assert driver.count("JsonUtility.ValidateMotorStateJson(json);") == 1\n    apply = driver[\n        driver.index("public void ApplyMotorJson") :\n        driver.index("private static void ValidatePosture")\n    ]\n    assert apply.index("JsonUtility.ValidateMotorStateJson(json);") < apply.index(\n        "JsonUtility.FromJson<MotorState>(json)"\n    )\n''',
    '''    apply = driver[\n        driver.index("public void ApplyMotorJson") :\n        driver.index("private static void ValidatePosture")\n    ]\n    validator_call = "var validatedVersion = JsonUtility.ValidateMotorStateJson("\n    assert apply.count(validator_call) == 1\n    assert apply.index(validator_call) < apply.index("JsonUtility.FromJson<MotorState>(json)")\n''',
    "guard driver ordering",
)
guard = replace_once(
    guard,
    '    assert "ValidateMotorStatePresenceAndTypes(json, true, out var validatedVersion);" in source\n',
    '    assert "ValidateMotorStatePresenceAndTypes(" in source\n    assert "out validatedDurationMs" in source\n    assert "out validatedSpeechElapsedMs" in source\n',
    "guard generic authority assertion",
)
GUARD.write_text(guard, encoding="utf-8")

version = VERSION.read_text(encoding="utf-8")
version = replace_once(
    version,
    '    assert "ValidateMotorStatePresenceAndTypes(json, true, out var validatedVersion);" in entry\n',
    '    assert "return ValidateMotorStateJson(json, out _, out _);" in entry\n    assert "out validatedDurationMs" in entry\n    assert "out validatedSpeechElapsedMs" in entry\n',
    "version validator entry",
)
version = replace_once(
    version,
    '    assert "out int? validatedVersion" in raw\n    assert "validatedVersion = null;" in raw\n',
    '    assert "out int? validatedVersion" in raw\n    assert "out int? validatedDurationMs" in raw\n    assert "out int? validatedSpeechElapsedMs" in raw\n    assert "validatedVersion = null;" in raw\n    assert "validatedDurationMs = null;" in raw\n    assert "validatedSpeechElapsedMs = null;" in raw\n',
    "version raw outputs",
)
version = replace_once(
    version,
    '    raw_call = "var validatedVersion = JsonUtility.ValidateMotorStateJson(json);"\n',
    '    raw_call = "var validatedVersion = JsonUtility.ValidateMotorStateJson("\n',
    "version driver raw call",
)
VERSION.write_text(version, encoding="utf-8")

TRANSPORT.write_text('''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\n\nREPO = Path(__file__).resolve().parents[1]\nUTILITY = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"\nDRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"\nSCHEMAS = [\n    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",\n    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",\n    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",\n]\n\n\ndef test_integer_wire_values_remain_raw_authoritative_across_all_schema_versions() -> None:\n    contracts = []\n    for path in SCHEMAS:\n        schema = json.loads(path.read_text(encoding="utf-8"))\n        contracts.append((\n            schema["properties"]["duration_ms"],\n            schema["properties"]["speech"]["properties"]["elapsed_ms"],\n        ))\n    assert all(contract == contracts[0] for contract in contracts[1:])\n    assert contracts[0][0] == {"type": "integer", "minimum": 0, "maximum": 120000}\n    assert contracts[0][1] == {"type": "integer", "minimum": 0, "maximum": 3600000}\n\n    utility = UTILITY.read_text(encoding="utf-8")\n    assert "out int? validatedDurationMs" in utility\n    assert "out int? validatedSpeechElapsedMs" in utility\n    assert "validatedDurationMs = ValidateDuration(root);" in utility\n    assert "validatedSpeechElapsedMs = ValidateSpeech(root);" in utility\n    assert "private static int? ValidateDuration" in utility\n    assert "private static int? ValidateSpeech" in utility\n    assert 'return RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L);' in utility\n    assert 'var elapsedMs = RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);' in utility\n    assert "return elapsedMs;" in utility\n\n\ndef test_unity_dto_cannot_reinterpret_integer_timing_tokens() -> None:\n    source = DRIVER.read_text(encoding="utf-8")\n    speech = source[source.index("private sealed class SpeechState") : source.index("private sealed class ObservedEmbodimentState")]\n    motor = source[source.index("private sealed class MotorState") : source.index("[SerializeField] private BodyRigAvatarLoader")]\n    assert "public int elapsed_ms { get; set; }" in speech\n    assert "public int elapsed_ms;" not in speech\n    assert "public int duration_ms { get; set; }" in motor\n    assert "public int duration_ms;" not in motor\n\n\ndef test_driver_injects_raw_canonical_integer_values_after_unity_deserialization() -> None:\n    source = DRIVER.read_text(encoding="utf-8")\n    apply = source[source.index("public void ApplyMotorJson") : source.index("private static void ValidatePosture")]\n    raw_call = "var validatedVersion = JsonUtility.ValidateMotorStateJson("\n    deserialize = "var next = JsonUtility.FromJson<MotorState>(json);"\n    version_assign = "next.version = validatedVersion;"\n    duration_assign = "next.duration_ms = validatedDurationMs ?? 0;"\n    parity_guard = "validatedSpeechElapsedMs.HasValue != (next.speech != null)"\n    elapsed_assign = "next.speech.elapsed_ms = validatedSpeechElapsedMs.Value;"\n    assert "out var validatedDurationMs, out var validatedSpeechElapsedMs" in apply\n    assert raw_call in apply and deserialize in apply\n    assert version_assign in apply and duration_assign in apply\n    assert parity_guard in apply and elapsed_assign in apply\n    assert apply.index(raw_call) < apply.index(deserialize) < apply.index(version_assign)\n    assert apply.index(version_assign) < apply.index(duration_assign)\n    assert apply.index(duration_assign) < apply.index('ValidateRange(next.duration_ms, 0.0f, 120000.0f, "duration_ms")')\n    assert apply.index(elapsed_assign) < apply.index("if (next.speech.elapsed_ms < 0 || next.speech.elapsed_ms > 3600000)")\n\n\ndef test_bounded_integer_canonicalization_reuses_exact_decimal_comparator() -> None:\n    source = UTILITY.read_text(encoding="utf-8")\n    helper = source[source.index("private static int RequireIntegerRangeToken") : source.index("private static void RequireExactFields")]\n    assert "RequireIntegerToken(raw, context);" in helper\n    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in helper\n    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in helper\n    assert "minimum < int.MinValue || maximum > int.MaxValue" in helper\n    assert "while (low <= high)" in helper\n    assert "CompareJsonNumberToInteger(raw, midpoint)" in helper\n    assert "double.Parse" not in helper\n    assert "float.Parse" not in helper\n    assert "decimal.Parse" not in helper\n''', encoding="utf-8")
