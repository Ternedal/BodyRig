from pathlib import Path

path = Path("reference-renderer/Assets/BodyRig/BodyRigJsonUtility.cs")
source = path.read_text(encoding="utf-8")

if "using System.Text;" not in source:
    source = source.replace("using System.Globalization;\n", "using System.Globalization;\nusing System.Text;\n", 1)

if "RootRequiredFields" not in source:
    anchor = '''        private static readonly string[] EmbodimentFields =\n        {\n            "source",\n            "observed",\n        };\n\n'''
    addition = anchor + '''        private static readonly string[] RootRequiredFields =\n        {\n            "type",\n            "version",\n            "body_id",\n            "utterance_id",\n            "motion",\n        };\n\n        private static readonly string[] RootV1AllowedFields =\n        {\n            "type", "version", "body_id", "utterance_id", "motion",\n            "expression", "gesture", "gaze", "posture", "duration_ms", "speech",\n        };\n\n        private static readonly string[] RootV2AllowedFields =\n        {\n            "type", "version", "body_id", "utterance_id", "motion",\n            "expression", "gesture", "gaze", "posture", "duration_ms", "speech", "embodiment",\n        };\n\n        private static readonly string[] RootV3AllowedFields =\n        {\n            "type", "version", "body_id", "utterance_id", "motion",\n            "expression", "gesture", "gaze", "posture", "duration_ms", "speech", "embodiment", "locomotion",\n        };\n\n'''
    if source.count(anchor) != 1:
        raise SystemExit(f"embodiment fields anchor count={source.count(anchor)}")
    source = source.replace(anchor, addition, 1)

guard_start = source.index("        private static void ValidateMotorStateV3PresenceAndTypes(string json)")
guard_end = source.index("        private static void ValidateMotion(string json)", guard_start)
new_guard = '''        private static void ValidateMotorStateV3PresenceAndTypes(string json)\n        {\n            if (string.IsNullOrWhiteSpace(json))\n            {\n                return;\n            }\n\n            // Select raw values structurally from the root object. Validators\n            // receive one-property synthetic documents so nested/ignored decoys\n            // can never satisfy a root Motor State field check.\n            var rootValues = CollectRootValues(json);\n            if (!rootValues.TryGetValue("type", out var rawType))\n            {\n                return;\n            }\n            if (rawType.Trim() != "\\\"bodyrig-motor-state\\\"")\n            {\n                return;\n            }\n            if (!rootValues.TryGetValue("version", out var rawVersion))\n            {\n                throw new ArgumentException("BodyRig Motor State requires integer version 1, 2 or 3");\n            }\n\n            int version;\n            switch (rawVersion.Trim())\n            {\n                case "1": version = 1; break;\n                case "2": version = 2; break;\n                case "3": version = 3; break;\n                default:\n                    throw new ArgumentException("BodyRig Motor State requires integer version 1, 2 or 3");\n            }\n\n            var rootFields = new HashSet<string>(rootValues.Keys, StringComparer.Ordinal);\n            RequireRequiredFields(rootFields, RootRequiredFields, "root");\n            RequireAllowedFields(\n                rootFields,\n                version == 1 ? RootV1AllowedFields : version == 2 ? RootV2AllowedFields : RootV3AllowedFields,\n                "root");\n            RequireStringToken(rootValues["body_id"], "root", "body_id");\n            RequireStringToken(rootValues["utterance_id"], "root", "utterance_id");\n\n            ValidateMotion(BuildSinglePropertyJson("motion", rootValues["motion"]));\n            if (rootValues.TryGetValue("expression", out var expression))\n                ValidateExpression(BuildSinglePropertyJson("expression", expression));\n            if (rootValues.TryGetValue("gesture", out var gesture))\n                ValidateGesture(BuildSinglePropertyJson("gesture", gesture));\n            if (rootValues.TryGetValue("gaze", out var gaze))\n                ValidateGaze(BuildSinglePropertyJson("gaze", gaze));\n            if (rootValues.TryGetValue("duration_ms", out var duration))\n                ValidateDuration(BuildSinglePropertyJson("duration_ms", duration));\n            if (rootValues.TryGetValue("speech", out var speech))\n                ValidateSpeech(BuildSinglePropertyJson("speech", speech));\n            if (rootValues.TryGetValue("embodiment", out var embodiment))\n                ValidateEmbodiment(BuildSinglePropertyJson("embodiment", embodiment), version);\n\n            if (version == 3)\n            {\n                if (rootValues.TryGetValue("posture", out var posture))\n                    ValidatePosture(BuildSinglePropertyJson("posture", posture));\n                if (rootValues.TryGetValue("locomotion", out var locomotion))\n                    ValidateLocomotion(BuildSinglePropertyJson("locomotion", locomotion));\n                return;\n            }\n\n            if (rootValues.TryGetValue("posture", out var legacyPosture))\n                ValidateLegacyPosture(BuildSinglePropertyJson("posture", legacyPosture));\n            if (rootValues.ContainsKey("locomotion"))\n            {\n                throw new ArgumentException("Motor State v1/v2 may not carry locomotion");\n            }\n        }\n\n'''
source = source[:guard_start] + new_guard + source[guard_end:]

shared_start = source.index("        private static void ValidateMotion(string json)")
shared_end = source.index("        private static void ValidateLegacyPosture(string json)", shared_start)
new_shared = '''        private static void ValidateMotion(string json)\n        {\n            var objectMatch = MotionObjectPattern.Match(json);\n            if (!objectMatch.Success)\n            {\n                throw new ArgumentException("Motor State motion must be a flat JSON object");\n            }\n            var body = objectMatch.Groups["body"].Value;\n            var values = CollectUniqueFieldValues(body, "motion");\n            var fields = new HashSet<string>(values.Keys, StringComparer.Ordinal);\n            RequireExactFields(fields, MotionFields, "motion");\n            RequireNumericToken(values["energy"], "motion", "energy");\n            RequireNumericToken(values["head_motion"], "motion", "head_motion");\n        }\n\n        private static void ValidateExpression(string json)\n        {\n            var objectMatch = ExpressionObjectPattern.Match(json);\n            if (!objectMatch.Success)\n            {\n                throw new ArgumentException("Motor State expression must be a flat JSON object");\n            }\n            var body = objectMatch.Groups["body"].Value;\n            var values = CollectUniqueFieldValues(body, "expression");\n            var fields = new HashSet<string>(values.Keys, StringComparer.Ordinal);\n            RequireExactFields(fields, ExpressionFields, "expression");\n            RequireStringToken(values["emotion"], "expression", "emotion");\n            RequireNumericToken(values["intensity"], "expression", "intensity");\n        }\n\n        private static void ValidateGesture(string json)\n        {\n            var objectMatch = GestureObjectPattern.Match(json);\n            if (!objectMatch.Success)\n            {\n                throw new ArgumentException("Motor State gesture must be a flat JSON object");\n            }\n            var body = objectMatch.Groups["body"].Value;\n            var values = CollectUniqueFieldValues(body, "gesture");\n            var fields = new HashSet<string>(values.Keys, StringComparer.Ordinal);\n            RequireExactFields(fields, GestureFields, "gesture");\n            RequireStringToken(values["id"], "gesture", "id");\n            RequireNumericToken(values["amplitude"], "gesture", "amplitude");\n        }\n\n        private static void ValidateGaze(string json)\n        {\n            var objectMatch = GazeObjectPattern.Match(json);\n            if (!objectMatch.Success)\n            {\n                throw new ArgumentException("Motor State gaze must be a flat JSON object");\n            }\n            var body = objectMatch.Groups["body"].Value;\n            var values = CollectUniqueFieldValues(body, "gaze");\n            var fields = new HashSet<string>(values.Keys, StringComparer.Ordinal);\n            RequireExactFields(fields, GazeFields, "gaze");\n            RequireStringToken(values["target"], "gaze", "target");\n            RequireNumericToken(values["strength"], "gaze", "strength");\n        }\n\n        private static void ValidateDuration(string json)\n        {\n            var root = CollectRootValues(json);\n            if (!root.TryGetValue("duration_ms", out var raw))\n            {\n                return;\n            }\n            RequireIntegerToken(raw, 0L, 120000L, "duration_ms", "duration_ms");\n        }\n\n        private static void ValidateSpeech(string json)\n        {\n            var objectMatch = SpeechObjectPattern.Match(json);\n            if (!objectMatch.Success)\n            {\n                throw new ArgumentException("Motor State speech must be a flat JSON object");\n            }\n            var body = objectMatch.Groups["body"].Value;\n            var values = CollectUniqueFieldValues(body, "speech");\n            var fields = new HashSet<string>(values.Keys, StringComparer.Ordinal);\n            RequireAllowedFields(fields, SpeechAllowedFields, "speech");\n            RequireRequiredFields(fields, SpeechRequiredFields, "speech");\n\n            var state = RequireStringToken(values["state"], "speech", "state");\n            if (state != "start" && state != "update" && state != "stop")\n            {\n                throw new ArgumentException("Motor State speech requires start/update/stop string state");\n            }\n            RequireIntegerToken(values["elapsed_ms"], 0L, 3600000L, "speech", "elapsed_ms");\n            if (values.TryGetValue("viseme", out var rawViseme))\n            {\n                var viseme = RequireStringToken(rawViseme, "speech", "viseme");\n                if (viseme.Length > 32 || !Regex.IsMatch(viseme, "^[A-Za-z0-9._-]+$", RegexOptions.CultureInvariant))\n                {\n                    throw new ArgumentException("Motor State speech viseme violates schema constraints");\n                }\n            }\n            if (values.TryGetValue("amplitude", out var amplitude))\n            {\n                RequireNumericToken(amplitude, "speech", "amplitude");\n            }\n        }\n\n        private static void ValidateEmbodiment(string json, int version)\n        {\n            if (version == 1)\n            {\n                throw new ArgumentException("Motor State v1 may not carry observed embodiment evidence");\n            }\n\n            var objectMatch = EmbodimentObjectPattern.Match(json);\n            if (!objectMatch.Success)\n            {\n                throw new ArgumentException("Motor State embodiment requires source plus flat observed object");\n            }\n\n            var outerBody =\n                objectMatch.Groups["before"].Value +\n                "\\\"observed\\\":0" +\n                objectMatch.Groups["after"].Value;\n            var outerValues = CollectUniqueFieldValues(outerBody, "embodiment");\n            var outerFields = new HashSet<string>(outerValues.Keys, StringComparer.Ordinal);\n            RequireExactFields(outerFields, EmbodimentFields, "embodiment");\n            var sourceValue = RequireStringToken(outerValues["source"], "embodiment", "source");\n            if (sourceValue != "modelrig-bodyprint-v1")\n            {\n                throw new ArgumentException("Motor State embodiment requires modelrig-bodyprint-v1 source");\n            }\n\n            var observedBody = objectMatch.Groups["observed"].Value;\n            var observedValues = CollectUniqueFieldValues(observedBody, "embodiment.observed");\n            if (observedValues.Count == 0)\n            {\n                throw new ArgumentException("Motor State embodiment.observed requires at least one field");\n            }\n            foreach (var pair in observedValues)\n            {\n                if (Array.IndexOf(ObservedEmbodimentFields, pair.Key) < 0)\n                {\n                    throw new ArgumentException($"Motor State embodiment contains unknown observed field: {pair.Key}");\n                }\n                RequireNumericToken(pair.Value, "embodiment.observed", pair.Key);\n            }\n        }\n\n'''
source = source[:shared_start] + new_shared + source[shared_end:]

collector_start = source.index("        private static HashSet<string> CollectRootFields(string json)")
collector_end = source.index("        private static void SkipJsonValue", collector_start)
new_collector = r'''        private static Dictionary<string, string> CollectRootValues(string json)
        {
            var trimmed = json.Trim();
            if (trimmed.Length < 2 || trimmed[0] != '{' || trimmed[trimmed.Length - 1] != '}')
            {
                throw new ArgumentException("Motor State must be one root JSON object");
            }
            return CollectUniqueFieldValues(trimmed.Substring(1, trimmed.Length - 2), "root");
        }

        private static Dictionary<string, string> CollectUniqueFieldValues(string body, string objectName)
        {
            var values = new Dictionary<string, string>(StringComparer.Ordinal);
            var index = 0;
            while (true)
            {
                SkipWhitespace(body, ref index);
                if (index >= body.Length)
                {
                    return values;
                }

                var key = ReadPropertyName(body, ref index, objectName);
                if (values.ContainsKey(key))
                {
                    throw new ArgumentException($"Motor State {objectName} contains duplicate field: {key}");
                }

                SkipWhitespace(body, ref index);
                if (index >= body.Length || body[index] != ':')
                {
                    throw new ArgumentException($"Motor State {objectName} contains malformed property: {key}");
                }
                index++;
                SkipWhitespace(body, ref index);
                var valueStart = index;
                SkipJsonValue(body, ref index, objectName);
                var rawValue = body.Substring(valueStart, index - valueStart).Trim();
                if (string.IsNullOrEmpty(rawValue))
                {
                    throw new ArgumentException($"Motor State {objectName} contains empty JSON value: {key}");
                }
                values.Add(key, rawValue);
                SkipWhitespace(body, ref index);

                if (index >= body.Length)
                {
                    return values;
                }
                if (body[index] != ',')
                {
                    throw new ArgumentException($"Motor State {objectName} contains malformed JSON object content");
                }
                index++;
                SkipWhitespace(body, ref index);
                if (index >= body.Length)
                {
                    throw new ArgumentException($"Motor State {objectName} may not end with a trailing comma");
                }
            }
        }

        private static HashSet<string> CollectUniqueFields(string body, string objectName)
        {
            return new HashSet<string>(CollectUniqueFieldValues(body, objectName).Keys, StringComparer.Ordinal);
        }

        private static string BuildSinglePropertyJson(string property, string rawValue)
        {
            return "{\"" + property + "\":" + rawValue + "}";
        }

        private static string ReadPropertyName(string text, ref int index, string objectName)
        {
            var key = ReadJsonString(text, ref index, objectName + " property name");
            if (string.IsNullOrEmpty(key))
            {
                throw new ArgumentException($"Motor State {objectName} contains empty property name");
            }
            return key;
        }

        private static string ReadJsonString(string text, ref int index, string context)
        {
            if (index >= text.Length || text[index] != '"')
            {
                throw new ArgumentException($"Motor State {context} requires JSON string token");
            }
            index++;
            var builder = new StringBuilder();
            while (index < text.Length)
            {
                var current = text[index++];
                if (current == '"')
                {
                    return builder.ToString();
                }
                if (current != '\\')
                {
                    if (current < 0x20)
                    {
                        throw new ArgumentException($"Motor State {context} contains control character");
                    }
                    builder.Append(current);
                    continue;
                }

                if (index >= text.Length)
                {
                    throw new ArgumentException($"Motor State {context} contains unterminated escape");
                }
                var escape = text[index++];
                switch (escape)
                {
                    case '"': builder.Append('"'); break;
                    case '\\': builder.Append('\\'); break;
                    case '/': builder.Append('/'); break;
                    case 'b': builder.Append('\b'); break;
                    case 'f': builder.Append('\f'); break;
                    case 'n': builder.Append('\n'); break;
                    case 'r': builder.Append('\r'); break;
                    case 't': builder.Append('\t'); break;
                    case 'u':
                        if (index + 4 > text.Length)
                        {
                            throw new ArgumentException($"Motor State {context} contains short unicode escape");
                        }
                        var hex = text.Substring(index, 4);
                        if (!int.TryParse(hex, NumberStyles.HexNumber, CultureInfo.InvariantCulture, out var codePoint))
                        {
                            throw new ArgumentException($"Motor State {context} contains invalid unicode escape");
                        }
                        builder.Append((char)codePoint);
                        index += 4;
                        break;
                    default:
                        throw new ArgumentException($"Motor State {context} contains invalid JSON escape");
                }
            }
            throw new ArgumentException($"Motor State {context} contains unterminated JSON string");
        }

        private static string RequireStringToken(string rawValue, string context, string field)
        {
            var index = 0;
            var value = ReadJsonString(rawValue, ref index, context + "." + field);
            SkipWhitespace(rawValue, ref index);
            if (index != rawValue.Length || string.IsNullOrEmpty(value))
            {
                throw new ArgumentException($"Motor State {context} requires non-empty string field: {field}");
            }
            return value;
        }

        private static void RequireNumericToken(string rawValue, string context, string field)
        {
            if (!Regex.IsMatch(rawValue.Trim(), "^(?:" + JsonNumberPattern + ")$", RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} requires numeric field: {field}");
            }
        }

        private static void RequireIntegerToken(
            string rawValue,
            long minimum,
            long maximum,
            string context,
            string field)
        {
            var trimmed = rawValue.Trim();
            if (!Regex.IsMatch(trimmed, "^(?:" + JsonIntegerPattern + ")$", RegexOptions.CultureInvariant) ||
                !long.TryParse(trimmed, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) ||
                value < minimum || value > maximum)
            {
                throw new ArgumentException($"Motor State {context} requires integer field in range: {field}");
            }
        }

'''
source = source[:collector_start] + new_collector + source[collector_end:]

path.write_text(source, encoding="utf-8")

shared_test = Path("tests/test_reference_renderer_json_shared_guard.py")
text = shared_test.read_text(encoding="utf-8")
text = text.replace("CollectRootFields(json)", "CollectRootValues(json)")
text = text.replace("private static HashSet<string> CollectRootFields", "private static Dictionary<string, string> CollectRootValues")
text = text.replace('assert "may not escape property names" in collector\n', 'assert "ReadJsonString" in collector\n    assert "NumberStyles.HexNumber" in collector\n')
if "test_root_scoping_blocks_nested_decoys_and_viseme_constraints_are_enforced" not in text:
    text += r'''


def test_root_scoping_blocks_nested_decoys_and_viseme_constraints_are_enforced() -> None:
    source = SHIM.read_text(encoding="utf-8")
    guard = source[
        source.index("private static void ValidateMotorStateV3PresenceAndTypes") :
        source.index("private static void ValidateMotion")
    ]
    speech = source[
        source.index("private static void ValidateSpeech") :
        source.index("private static void ValidateEmbodiment")
    ]

    assert "CollectRootValues(json)" in guard
    assert "BuildSinglePropertyJson" in guard
    for field in ("motion", "expression", "gesture", "gaze", "duration_ms", "speech", "embodiment"):
        assert field in guard
    assert "RootRequiredFields" in guard
    assert "RootV1AllowedFields" in guard
    assert "RootV2AllowedFields" in guard
    assert "RootV3AllowedFields" in guard
    assert "CollectUniqueFieldValues(body, \"speech\")" in speech
    assert "RequireIntegerToken(values[\"elapsed_ms\"]" in speech
    assert "RequireNumericToken(amplitude" in speech
    assert "viseme.Length > 32" in speech
    assert '"^[A-Za-z0-9._-]+$"' in speech
'''
shared_test.write_text(text, encoding="utf-8")

old_test = Path("tests/test_reference_renderer_json_utility_guard.py")
old = old_test.read_text(encoding="utf-8")
old = old.replace('    assert "!MotorTypePattern.IsMatch(json)" in source\n    assert "!VersionThreePattern.IsMatch(json)" in source\n', '    assert "CollectRootValues(json)" in source\n    assert "BuildSinglePropertyJson" in source\n')
old = old.replace('    assert "ValidatePosture(json);" in validate\n    assert "ValidateLocomotion(json);" in validate\n', '    assert "ValidatePosture(BuildSinglePropertyJson" in validate\n    assert "ValidateLocomotion(BuildSinglePropertyJson" in validate\n')
old_test.write_text(old, encoding="utf-8")
