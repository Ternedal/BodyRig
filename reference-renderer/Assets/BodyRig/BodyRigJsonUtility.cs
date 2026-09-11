using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Namespace-local shim around UnityEngine.JsonUtility.
    ///
    /// Unity's serializer maps missing or structurally incompatible numeric JSON
    /// members to CLR zero and can erase malformed optional objects to null. Raw
    /// Motor State validation therefore runs before deserialization, preserving
    /// the canonical presence/type boundary for v1/v2/v3 while leaving ordinary
    /// JsonUtility payloads untouched.
    /// </summary>
    internal static class JsonUtility
    {
        private const string JsonNumberPattern =
            "-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?";
        private const string JsonIntegerPattern = "-?(?:0|[1-9][0-9]*)";
        private const string BodyIdPattern = @"\A[a-z0-9æøå_-]+\z";
        private const string LowerIdentifierPattern = @"\A[a-z0-9_-]+\z";
        private const string UtteranceIdPattern = @"\A[A-Za-z0-9._:-]+\z";
        private const string VisemePattern = @"\A[A-Za-z0-9._-]+\z";

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
            "locomotion",
            "duration_ms",
            "speech",
            "embodiment",
        };

        private static readonly string[] MotionFields =
        {
            "energy",
            "head_motion",
        };

        private static readonly string[] ExpressionFields =
        {
            "emotion",
            "intensity",
        };

        private static readonly string[] GestureFields =
        {
            "id",
            "amplitude",
        };

        private static readonly string[] GazeFields =
        {
            "target",
            "strength",
        };

        private static readonly string[] SpeechAllowedFields =
        {
            "state",
            "elapsed_ms",
            "viseme",
            "amplitude",
        };

        private static readonly string[] SpeechRequiredFields =
        {
            "state",
            "elapsed_ms",
        };

        private static readonly string[] GenericPostureFields =
        {
            "id",
            "intensity",
        };

        private static readonly string[] NaturalPostureFields =
        {
            "id",
            "source",
            "intensity",
            "torso_forward_lean_degrees",
            "torso_right_lean_degrees",
            "shoulder_roll_degrees",
            "hip_roll_degrees",
            "head_forward_offset_to_height",
            "head_right_offset_to_height",
        };

        private static readonly string[] WalkLocomotionFields =
        {
            "action",
            "effort",
            "transition_intensity",
            "cadence_spm",
            "stride_length_to_height",
            "stance_width_to_height",
            "vertical_bounce_to_height",
            "left_arm_swing_to_height",
            "right_arm_swing_to_height",
            "arm_swing_to_height",
        };

        private static readonly string[] TurnLocomotionFields =
        {
            "action",
            "effort",
            "transition_intensity",
            "turn_speed_degrees_per_second",
        };

        private static readonly string[] StopLocomotionFields =
        {
            "action",
            "effort",
            "transition_intensity",
        };

        private static readonly string[] ObservedEmbodimentFields =
        {
            "energy",
            "gesture_frequency",
            "gesture_amplitude",
            "head_motion",
            "turn_speed",
            "walk_cadence_spm",
            "posture_torso_lean_degrees",
            "posture_torso_forward_lean_degrees",
            "posture_torso_right_lean_degrees",
            "posture_shoulder_tilt_degrees",
            "posture_shoulder_roll_degrees",
            "posture_hip_tilt_degrees",
            "posture_hip_roll_degrees",
            "posture_head_offset_to_height",
            "posture_head_forward_offset_to_height",
            "posture_head_right_offset_to_height",
            "stride_length_to_height",
            "stance_width_to_height",
            "vertical_bounce_to_height",
            "left_arm_swing_to_height",
            "right_arm_swing_to_height",
            "arm_swing_to_height",
            "arm_swing_asymmetry",
            "turn_speed_degrees_per_second",
            "transition_intensity",
            "idle_sway_to_height",
            "blink_rate_per_min",
            "gaze_strength",
            "head_tilt",
            "speech_motion",
            "idle_strength",
            "gaze_smoothing",
            "gesture_intensity",
            "breathing_strength",
        };

        public static T FromJson<T>(string json)
        {
            ValidateMotorStatePresenceAndTypes(json);
            return UnityEngine.JsonUtility.FromJson<T>(json);
        }

        public static object FromJson(string json, Type type)
        {
            ValidateMotorStatePresenceAndTypes(json);
            return UnityEngine.JsonUtility.FromJson(json, type);
        }

        public static void FromJsonOverwrite(string json, object objectToOverwrite)
        {
            ValidateMotorStatePresenceAndTypes(json);
            UnityEngine.JsonUtility.FromJsonOverwrite(json, objectToOverwrite);
        }

        public static string ToJson(object obj)
        {
            return UnityEngine.JsonUtility.ToJson(obj);
        }

        public static string ToJson(object obj, bool prettyPrint)
        {
            return UnityEngine.JsonUtility.ToJson(obj, prettyPrint);
        }

        private static void ValidateMotorStatePresenceAndTypes(string json)
        {
            if (string.IsNullOrEmpty(json))
            {
                return;
            }

            var probeIndex = 0;
            SkipWhitespace(json, ref probeIndex);
            if (probeIndex < json.Length && IsNonJsonWhitespace(json[probeIndex]))
            {
                throw new ArgumentException("Motor State JSON contains non-RFC whitespace");
            }
            if (probeIndex >= json.Length || json[probeIndex] != '{')
            {
                return;
            }

            var root = ParseObjectMembers(json, "root");
            if (!root.TryGetValue("type", out var rawType))
            {
                return;
            }
            if (!TryParseStringToken(rawType, out var type) || type != "bodyrig-motor-state")
            {
                return;
            }

            if (!root.TryGetValue("version", out var rawVersion) ||
                !Regex.IsMatch(rawVersion, "^[123]$", RegexOptions.CultureInvariant))
            {
                throw new ArgumentException("Motor State requires integer version 1, 2, or 3");
            }
            var version = int.Parse(rawVersion);

            RequireAllowedFields(root, RootFieldsForVersion(version), $"root v{version}");
            RequireConstrainedStringMember(root, "body_id", "root", 1, 160, BodyIdPattern);
            RequireConstrainedStringMember(root, "utterance_id", "root", 1, 160, UtteranceIdPattern);
            ValidateRequiredExactObject(root, "motion", MotionFields, "motion", Array.Empty<string>());
            ValidateObjectNumericRange(root, "motion", "energy", "motion", 0L, 1L);
            ValidateObjectNumericRange(root, "motion", "head_motion", "motion", 0L, 1L);
            ValidateOptionalExactObject(root, "expression", ExpressionFields, "expression", new[] { "emotion" });
            ValidateOptionalObjectStringConstraint(
                root, "expression", "emotion", "expression", 1, 64, LowerIdentifierPattern);
            ValidateObjectNumericRange(root, "expression", "intensity", "expression", 0L, 1L);
            ValidateOptionalExactObject(root, "gesture", GestureFields, "gesture", new[] { "id" });
            ValidateOptionalObjectStringConstraint(
                root, "gesture", "id", "gesture", 1, 80, LowerIdentifierPattern);
            ValidateObjectNumericRange(root, "gesture", "amplitude", "gesture", 0L, 1L);
            ValidateOptionalExactObject(root, "gaze", GazeFields, "gaze", new[] { "target" });
            ValidateOptionalObjectStringConstraint(root, "gaze", "target", "gaze", 1, 127, null);
            ValidateObjectNumericRange(root, "gaze", "strength", "gaze", 0L, 1L);
            ValidateDuration(root);
            ValidateSpeech(root);
            ValidatePosture(root, version);
            ValidateEmbodiment(root, version);
            ValidateLocomotion(root, version);
        }

        private static string[] RootFieldsForVersion(int version)
        {
            switch (version)
            {
                case 1: return RootV1Fields;
                case 2: return RootV2Fields;
                case 3: return RootV3Fields;
                default: throw new ArgumentOutOfRangeException(nameof(version));
            }
        }

        private static void ValidateRequiredExactObject(
            Dictionary<string, string> parent,
            string propertyName,
            string[] expected,
            string context,
            string[] stringFields)
        {
            if (!parent.TryGetValue(propertyName, out var raw))
            {
                throw new ArgumentException($"Motor State requires {context} object");
            }
            ValidateExactObject(raw, expected, context, stringFields);
        }

        private static void ValidateOptionalExactObject(
            Dictionary<string, string> parent,
            string propertyName,
            string[] expected,
            string context,
            string[] stringFields)
        {
            if (!parent.TryGetValue(propertyName, out var raw))
            {
                return;
            }
            ValidateExactObject(raw, expected, context, stringFields);
        }

        private static void ValidateOptionalObjectStringConstraint(
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
            var fields = ParseObjectMembers(raw, context);
            RequireConstrainedStringMember(
                fields, field, context, minimumLength, maximumLength, pattern);
        }

        private static void ValidateObjectNumericRange(
            Dictionary<string, string> parent,
            string propertyName,
            string field,
            string context,
            long minimum,
            long maximum,
            bool exclusiveMinimum = false)
        {
            if (!parent.TryGetValue(propertyName, out var raw))
            {
                return;
            }
            var fields = ParseObjectMembers(raw, context);
            RequireNumericRangeMember(fields, field, context, minimum, maximum, exclusiveMinimum);
        }

        private static void ValidateExactObject(
            string raw,
            string[] expected,
            string context,
            string[] stringFields)
        {
            var fields = ParseObjectMembers(raw, context);
            RequireExactFields(fields, expected, context);
            RequireNumericFields(fields, expected, context, stringFields);
            foreach (var field in stringFields)
            {
                RequireStringMember(fields, field, context);
            }
        }

        private static void ValidateDuration(Dictionary<string, string> root)
        {
            if (root.TryGetValue("duration_ms", out var raw))
            {
                RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L);
            }
        }

        private static void ValidateSpeech(Dictionary<string, string> root)
        {
            if (!root.TryGetValue("speech", out var raw))
            {
                return;
            }

            var fields = ParseObjectMembers(raw, "speech");
            RequireAllowedAndRequiredFields(fields, SpeechAllowedFields, SpeechRequiredFields, "speech");
            var state = RequireStringMember(fields, "state", "speech");
            if (state != "start" && state != "update" && state != "stop")
            {
                throw new ArgumentException("Motor State speech state must be start, update, or stop");
            }
            RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L);
            if (fields.ContainsKey("viseme"))
            {
                RequireConstrainedStringMember(fields, "viseme", "speech", 1, 32, VisemePattern);
            }
            if (fields.ContainsKey("amplitude"))
            {
                RequireNumericRangeMember(fields, "amplitude", "speech", 0L, 1L);
            }
        }

        private static void ValidatePosture(Dictionary<string, string> root, int version)
        {
            if (!root.TryGetValue("posture", out var raw))
            {
                return;
            }

            var fields = ParseObjectMembers(raw, "posture");
            var id = RequireConstrainedStringMember(
                fields, "id", "posture", 1, 80, LowerIdentifierPattern);
            RequireNumericRangeMember(fields, "intensity", "posture", 0L, 1L);
            if (fields.ContainsKey("source"))
            {
                var source = RequireStringMember(fields, "source", "posture");
                if (version != 3 || id != "natural" || source != "modelrig-bodyprint-v1")
                {
                    throw new ArgumentException(
                        "Motor State source-derived posture requires v3 natural id and modelrig-bodyprint-v1 source");
                }
                RequireExactFields(fields, NaturalPostureFields, "source-derived natural posture");
                RequireNumericFields(
                    fields, NaturalPostureFields, "source-derived natural posture", "id", "source");
                RequireNumericRangeMember(fields, "torso_forward_lean_degrees", "posture", -90L, 90L);
                RequireNumericRangeMember(fields, "torso_right_lean_degrees", "posture", -90L, 90L);
                RequireNumericRangeMember(fields, "shoulder_roll_degrees", "posture", -90L, 90L);
                RequireNumericRangeMember(fields, "hip_roll_degrees", "posture", -90L, 90L);
                RequireNumericRangeMember(fields, "head_forward_offset_to_height", "posture", -1L, 1L);
                RequireNumericRangeMember(fields, "head_right_offset_to_height", "posture", -1L, 1L);
                return;
            }

            RequireExactFields(fields, GenericPostureFields, $"posture {id}");
            RequireNumericFields(fields, GenericPostureFields, $"posture {id}", "id");
        }

        private static void ValidateEmbodiment(Dictionary<string, string> root, int version)
        {
            if (!root.TryGetValue("embodiment", out var raw))
            {
                return;
            }
            if (version < 2)
            {
                throw new ArgumentException("Motor State v1 may not carry embodiment");
            }

            var embodiment = ParseObjectMembers(raw, "embodiment");
            RequireExactFields(embodiment, new[] { "source", "observed" }, "embodiment");
            var source = RequireStringMember(embodiment, "source", "embodiment");
            if (source != "modelrig-bodyprint-v1")
            {
                throw new ArgumentException("Motor State embodiment requires modelrig-bodyprint-v1 source");
            }

            var observed = ParseObjectMembers(embodiment["observed"], "embodiment.observed");
            if (observed.Count == 0)
            {
                throw new ArgumentException("Motor State embodiment.observed requires at least one field");
            }
            RequireAllowedFields(observed, ObservedEmbodimentFields, "embodiment.observed");
            foreach (var field in observed.Keys)
            {
                RequireNumericMember(observed, field, "embodiment.observed");
                ValidateObservedEmbodimentNumericRange(observed, field);
            }
        }

        private static void ValidateObservedEmbodimentNumericRange(
            Dictionary<string, string> observed,
            string field)
        {
            switch (field)
            {
                case "energy":
                case "gesture_frequency":
                case "gesture_amplitude":
                case "head_motion":
                case "turn_speed":
                case "posture_head_offset_to_height":
                case "stance_width_to_height":
                case "vertical_bounce_to_height":
                case "arm_swing_asymmetry":
                case "transition_intensity":
                case "idle_sway_to_height":
                case "gaze_strength":
                case "head_tilt":
                case "speech_motion":
                case "idle_strength":
                case "gaze_smoothing":
                case "gesture_intensity":
                case "breathing_strength":
                    RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 1L);
                    return;
                case "walk_cadence_spm":
                    RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 300L);
                    return;
                case "posture_torso_lean_degrees":
                case "posture_shoulder_tilt_degrees":
                case "posture_hip_tilt_degrees":
                    RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 90L);
                    return;
                case "posture_torso_forward_lean_degrees":
                case "posture_torso_right_lean_degrees":
                case "posture_shoulder_roll_degrees":
                case "posture_hip_roll_degrees":
                    RequireNumericRangeMember(observed, field, "embodiment.observed", -90L, 90L);
                    return;
                case "posture_head_forward_offset_to_height":
                case "posture_head_right_offset_to_height":
                    RequireNumericRangeMember(observed, field, "embodiment.observed", -1L, 1L);
                    return;
                case "stride_length_to_height":
                case "left_arm_swing_to_height":
                case "right_arm_swing_to_height":
                case "arm_swing_to_height":
                    RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 2L);
                    return;
                case "turn_speed_degrees_per_second":
                    RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 720L);
                    return;
                case "blink_rate_per_min":
                    RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 120L);
                    return;
                default:
                    throw new ArgumentException(
                        $"Motor State embodiment.observed has no canonical numeric range for field: {field}");
            }
        }

        private static void ValidateLocomotion(Dictionary<string, string> root, int version)
        {
            if (!root.TryGetValue("locomotion", out var raw))
            {
                return;
            }
            if (version != 3)
            {
                throw new ArgumentException("Locomotion requires Motor State v3");
            }

            var fields = ParseObjectMembers(raw, "locomotion");
            var action = RequireStringMember(fields, "action", "locomotion");
            switch (action)
            {
                case "walk":
                    RequireExactFields(fields, WalkLocomotionFields, action);
                    RequireNumericFields(fields, WalkLocomotionFields, action, "action");
                    RequireNumericRangeMember(fields, "effort", "locomotion", 0L, 1L);
                    RequireNumericRangeMember(fields, "transition_intensity", "locomotion", 0L, 1L);
                    RequireNumericRangeMember(fields, "cadence_spm", "locomotion", 30L, 240L);
                    RequireNumericRangeMember(fields, "stride_length_to_height", "locomotion", 0L, 2L);
                    RequireNumericRangeMember(fields, "stance_width_to_height", "locomotion", 0L, 1L);
                    RequireNumericRangeMember(fields, "vertical_bounce_to_height", "locomotion", 0L, 1L);
                    RequireNumericRangeMember(fields, "left_arm_swing_to_height", "locomotion", 0L, 2L);
                    RequireNumericRangeMember(fields, "right_arm_swing_to_height", "locomotion", 0L, 2L);
                    RequireNumericRangeMember(fields, "arm_swing_to_height", "locomotion", 0L, 2L);
                    return;
                case "turn_left":
                case "turn_right":
                    RequireExactFields(fields, TurnLocomotionFields, action);
                    RequireNumericFields(fields, TurnLocomotionFields, action, "action");
                    RequireNumericRangeMember(fields, "effort", "locomotion", 0L, 1L);
                    RequireNumericRangeMember(fields, "transition_intensity", "locomotion", 0L, 1L);
                    RequireNumericRangeMember(
                        fields, "turn_speed_degrees_per_second", "locomotion", 0L, 720L, true);
                    return;
                case "stop":
                    RequireExactFields(fields, StopLocomotionFields, action);
                    RequireNumericFields(fields, StopLocomotionFields, action, "action");
                    RequireNumericRangeMember(fields, "effort", "locomotion", 0L, 1L);
                    RequireNumericRangeMember(fields, "transition_intensity", "locomotion", 0L, 1L);
                    return;
                default:
                    throw new ArgumentException($"Unsupported Motor State v3 locomotion action: {action}");
            }
        }

        private static Dictionary<string, string> ParseObjectMembers(string json, string context)
        {
            var index = 0;
            SkipWhitespace(json, ref index);
            if (index >= json.Length || json[index] != '{')
            {
                throw new ArgumentException($"Motor State {context} must be a JSON object");
            }
            index++;

            var members = new Dictionary<string, string>(StringComparer.Ordinal);
            SkipWhitespace(json, ref index);
            if (index < json.Length && json[index] == '}')
            {
                index++;
                EnsureOnlyTrailingWhitespace(json, index, context);
                return members;
            }

            while (index < json.Length)
            {
                SkipWhitespace(json, ref index);
                var key = ReadJsonString(json, ref index, context + " field name");
                SkipWhitespace(json, ref index);
                if (index >= json.Length || json[index] != ':')
                {
                    throw new ArgumentException($"Motor State {context} field {key} is missing ':'");
                }
                index++;
                SkipWhitespace(json, ref index);

                var valueStart = index;
                SkipJsonValue(json, ref index, context + "." + key);
                var rawValue = json.Substring(valueStart, index - valueStart);
                if (!members.TryAdd(key, rawValue))
                {
                    throw new ArgumentException($"Motor State {context} contains duplicate field: {key}");
                }

                SkipWhitespace(json, ref index);
                if (index >= json.Length)
                {
                    throw new ArgumentException($"Motor State {context} object is not closed");
                }
                if (json[index] == ',')
                {
                    index++;
                    continue;
                }
                if (json[index] == '}')
                {
                    index++;
                    EnsureOnlyTrailingWhitespace(json, index, context);
                    return members;
                }
                throw new ArgumentException($"Motor State {context} has invalid JSON object syntax");
            }

            throw new ArgumentException($"Motor State {context} object is not closed");
        }

        private static void SkipJsonValue(string json, ref int index, string context)
        {
            SkipWhitespace(json, ref index);
            if (index >= json.Length)
            {
                throw new ArgumentException($"Motor State {context} is missing a value");
            }

            if (json[index] == '"')
            {
                ReadJsonString(json, ref index, context);
                return;
            }
            if (json[index] == '{' || json[index] == '[')
            {
                SkipComposite(json, ref index, context);
                return;
            }

            var start = index;
            while (index < json.Length &&
                   !IsJsonWhitespace(json[index]) &&
                   json[index] != ',' && json[index] != '}' && json[index] != ']')
            {
                index++;
            }
            if (index == start)
            {
                throw new ArgumentException($"Motor State {context} has an invalid value");
            }
        }

        private static void SkipComposite(string json, ref int index, string context)
        {
            var stack = new Stack<char>();
            stack.Push(json[index] == '{' ? '}' : ']');
            index++;

            while (index < json.Length)
            {
                var current = json[index];
                if (current == '"')
                {
                    ReadJsonString(json, ref index, context);
                    continue;
                }
                if (current == '{')
                {
                    stack.Push('}');
                    index++;
                    continue;
                }
                if (current == '[')
                {
                    stack.Push(']');
                    index++;
                    continue;
                }
                if (current == '}' || current == ']')
                {
                    if (stack.Count == 0 || stack.Pop() != current)
                    {
                        throw new ArgumentException($"Motor State {context} has mismatched JSON delimiters");
                    }
                    index++;
                    if (stack.Count == 0)
                    {
                        return;
                    }
                    continue;
                }
                index++;
            }

            throw new ArgumentException($"Motor State {context} value is not closed");
        }

        private static string ReadJsonString(string json, ref int index, string context)
        {
            if (index >= json.Length || json[index] != '"')
            {
                throw new ArgumentException($"Motor State {context} requires a JSON string");
            }
            index++;
            var result = new StringBuilder();
            while (index < json.Length)
            {
                var current = json[index++];
                if (current == '"')
                {
                    return result.ToString();
                }
                if (current < 0x20)
                {
                    throw new ArgumentException($"Motor State {context} contains an invalid control character");
                }
                if (current != '\\')
                {
                    result.Append(current);
                    continue;
                }
                if (index >= json.Length)
                {
                    throw new ArgumentException($"Motor State {context} has an incomplete JSON escape");
                }

                var escape = json[index++];
                switch (escape)
                {
                    case '"': result.Append('"'); break;
                    case '\\': result.Append('\\'); break;
                    case '/': result.Append('/'); break;
                    case 'b': result.Append('\b'); break;
                    case 'f': result.Append('\f'); break;
                    case 'n': result.Append('\n'); break;
                    case 'r': result.Append('\r'); break;
                    case 't': result.Append('\t'); break;
                    case 'u':
                        if (index + 4 > json.Length)
                        {
                            throw new ArgumentException($"Motor State {context} has an incomplete unicode escape");
                        }
                        var code = 0;
                        for (var offset = 0; offset < 4; offset++)
                        {
                            var hex = HexValue(json[index + offset]);
                            if (hex < 0)
                            {
                                throw new ArgumentException($"Motor State {context} has an invalid unicode escape");
                            }
                            code = (code << 4) | hex;
                        }
                        result.Append((char)code);
                        index += 4;
                        break;
                    default:
                        throw new ArgumentException($"Motor State {context} has an invalid JSON escape");
                }
            }

            throw new ArgumentException($"Motor State {context} string is not closed");
        }

        private static int HexValue(char value)
        {
            if (value >= '0' && value <= '9') return value - '0';
            if (value >= 'a' && value <= 'f') return value - 'a' + 10;
            if (value >= 'A' && value <= 'F') return value - 'A' + 10;
            return -1;
        }

        private static bool IsJsonWhitespace(char value)
        {
            return value == ' ' || value == '\t' || value == '\n' || value == '\r';
        }

        private static bool IsNonJsonWhitespace(char value)
        {
            return char.IsWhiteSpace(value) && !IsJsonWhitespace(value);
        }

        private static void SkipWhitespace(string json, ref int index)
        {
            while (index < json.Length && IsJsonWhitespace(json[index])) index++;
        }

        private static void EnsureOnlyTrailingWhitespace(string json, int index, string context)
        {
            while (index < json.Length && IsJsonWhitespace(json[index])) index++;
            if (index != json.Length)
            {
                throw new ArgumentException($"Motor State {context} has trailing JSON content");
            }
        }

        private static bool TryParseStringToken(string raw, out string value)
        {
            value = null;
            var index = 0;
            try
            {
                SkipWhitespace(raw, ref index);
                if (index >= raw.Length || raw[index] != '"') return false;
                value = ReadJsonString(raw, ref index, "string token");
                SkipWhitespace(raw, ref index);
                return index == raw.Length;
            }
            catch (ArgumentException)
            {
                value = null;
                return false;
            }
        }

        private static string RequireStringMember(
            Dictionary<string, string> members,
            string field,
            string context)
        {
            if (!members.TryGetValue(field, out var raw))
            {
                throw new ArgumentException($"Motor State {context} is missing required field: {field}");
            }
            if (!TryParseStringToken(raw, out var value))
            {
                throw new ArgumentException($"Motor State {context} requires string field: {field}");
            }
            return value;
        }

        private static string RequireConstrainedStringMember(
            Dictionary<string, string> members,
            string field,
            string context,
            int minimumLength,
            int maximumLength,
            string pattern)
        {
            var value = RequireStringMember(members, field, context);
            var scalarLength = CountUnicodeScalars(value, context + "." + field);
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

        private static int CountUnicodeScalars(string value, string context)
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

        private static void RequireNumericMember(
            Dictionary<string, string> members,
            string field,
            string context)
        {
            if (!members.TryGetValue(field, out var raw))
            {
                throw new ArgumentException($"Motor State {context} is missing required field: {field}");
            }
            RequireNumericToken(raw, context + "." + field);
        }

        private static void RequireNumericRangeMember(
            Dictionary<string, string> members,
            string field,
            string context,
            long minimum,
            long maximum,
            bool exclusiveMinimum = false)
        {
            if (!members.TryGetValue(field, out var raw))
            {
                throw new ArgumentException($"Motor State {context} is missing required field: {field}");
            }
            RequireNumericRangeToken(
                raw, context + "." + field, minimum, maximum, exclusiveMinimum);
        }

        private static void RequireIntegerMember(
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

        private static void RequireIntegerRangeMember(
            Dictionary<string, string> members,
            string field,
            string context,
            long minimum,
            long maximum)
        {
            if (!members.TryGetValue(field, out var raw))
            {
                throw new ArgumentException($"Motor State {context} is missing required field: {field}");
            }
            RequireIntegerRangeToken(raw, context + "." + field, minimum, maximum);
        }

        private static void RequireNumericToken(string raw, string context)
        {
            if (!Regex.IsMatch(raw, "^(?:" + JsonNumberPattern + ")$", RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} requires a numeric JSON token");
            }
        }

        private static void RequireNumericRangeToken(
            string raw,
            string context,
            long minimum,
            long maximum,
            bool exclusiveMinimum)
        {
            RequireNumericToken(raw, context);
            var lowerComparison = CompareJsonNumberToInteger(raw, minimum);
            var upperComparison = CompareJsonNumberToInteger(raw, maximum);
            if (lowerComparison < 0 ||
                (exclusiveMinimum && lowerComparison == 0) ||
                upperComparison > 0)
            {
                var lowerOperator = exclusiveMinimum ? ">" : ">=";
                throw new ArgumentOutOfRangeException(
                    context,
                    $"Motor State numeric value must be {lowerOperator} {minimum} and <= {maximum}");
            }
        }

        private static int CompareJsonNumberToInteger(string raw, long integer)
        {
            var token = raw;
            var cursor = 0;
            var sign = 1;
            if (token[cursor] == '-')
            {
                sign = -1;
                cursor++;
            }

            var exponentIndex = token.IndexOf('e', cursor);
            if (exponentIndex < 0)
            {
                exponentIndex = token.IndexOf('E', cursor);
            }
            var mantissaEnd = exponentIndex >= 0 ? exponentIndex : token.Length;
            var dotIndex = token.IndexOf('.', cursor, mantissaEnd - cursor);
            var fractionalDigits = dotIndex >= 0 ? mantissaEnd - dotIndex - 1 : 0;

            var digitsBuilder = new StringBuilder(mantissaEnd - cursor);
            for (var index = cursor; index < mantissaEnd; index++)
            {
                if (token[index] != '.') digitsBuilder.Append(token[index]);
            }
            var digits = digitsBuilder.ToString().TrimStart('0');
            if (digits.Length == 0)
            {
                if (integer == 0L) return 0;
                return integer > 0L ? -1 : 1;
            }

            long explicitExponent = 0L;
            if (exponentIndex >= 0)
            {
                var exponentToken = token.Substring(exponentIndex + 1);
                if (!long.TryParse(
                        exponentToken,
                        NumberStyles.AllowLeadingSign,
                        CultureInfo.InvariantCulture,
                        out explicitExponent))
                {
                    explicitExponent = exponentToken[0] == '-' ? long.MinValue : long.MaxValue;
                }
            }
            var exponent10 = SaturatingSubtract(explicitExponent, fractionalDigits);

            var integerSign = integer == 0L ? 0 : integer < 0L ? -1 : 1;
            if (sign != integerSign)
            {
                return sign.CompareTo(integerSign);
            }
            if (integerSign == 0)
            {
                return 0;
            }

            var integerDigits = integer == long.MinValue
                ? "9223372036854775808"
                : Math.Abs(integer).ToString(CultureInfo.InvariantCulture);
            var magnitudeComparison = CompareDecimalMagnitude(digits, exponent10, integerDigits);
            return sign > 0 ? magnitudeComparison : -magnitudeComparison;
        }

        private static int CompareDecimalMagnitude(
            string digits,
            long exponent10,
            string integerDigits)
        {
            var leftOrder = SaturatingAdd(exponent10, digits.Length);
            var rightOrder = (long)integerDigits.Length;
            if (leftOrder != rightOrder)
            {
                return leftOrder < rightOrder ? -1 : 1;
            }

            var maximumDigits = Math.Max(digits.Length, integerDigits.Length);
            for (var index = 0; index < maximumDigits; index++)
            {
                var left = index < digits.Length ? digits[index] : '0';
                var right = index < integerDigits.Length ? integerDigits[index] : '0';
                if (left == right) continue;
                return left < right ? -1 : 1;
            }
            return 0;
        }

        private static long SaturatingAdd(long value, int addend)
        {
            if (value > long.MaxValue - addend) return long.MaxValue;
            if (value < long.MinValue + addend) return long.MinValue;
            return value + addend;
        }

        private static long SaturatingSubtract(long value, int subtrahend)
        {
            if (value < long.MinValue + subtrahend) return long.MinValue;
            if (value > long.MaxValue - subtrahend) return long.MaxValue;
            return value - subtrahend;
        }

        private static void RequireIntegerToken(string raw, string context)
        {
            if (!Regex.IsMatch(raw, "^(?:" + JsonIntegerPattern + ")$", RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} requires an integer JSON token");
            }
        }

        private static void RequireIntegerRangeToken(
            string raw,
            string context,
            long minimum,
            long maximum)
        {
            RequireIntegerToken(raw, context);
            if (!long.TryParse(
                    raw,
                    NumberStyles.AllowLeadingSign,
                    CultureInfo.InvariantCulture,
                    out var value) ||
                value < minimum || value > maximum)
            {
                throw new ArgumentOutOfRangeException(
                    context,
                    $"Motor State integer value must be in {minimum}..{maximum}");
            }
        }

        private static void RequireExactFields(
            Dictionary<string, string> actual,
            string[] expected,
            string context)
        {
            if (actual.Count != expected.Length)
            {
                throw new ArgumentException($"Motor State field set does not match {context}");
            }
            foreach (var field in expected)
            {
                if (!actual.ContainsKey(field))
                {
                    throw new ArgumentException($"Motor State {context} is missing required field: {field}");
                }
            }
        }

        private static void RequireAllowedAndRequiredFields(
            Dictionary<string, string> actual,
            string[] allowed,
            string[] required,
            string context)
        {
            RequireAllowedFields(actual, allowed, context);
            foreach (var field in required)
            {
                if (!actual.ContainsKey(field))
                {
                    throw new ArgumentException($"Motor State {context} is missing required field: {field}");
                }
            }
        }

        private static void RequireAllowedFields(
            Dictionary<string, string> actual,
            string[] allowed,
            string context)
        {
            foreach (var field in actual.Keys)
            {
                if (Array.IndexOf(allowed, field) < 0)
                {
                    throw new ArgumentException($"Motor State {context} contains unsupported field: {field}");
                }
            }
        }

        private static void RequireNumericFields(
            Dictionary<string, string> actual,
            string[] expected,
            string context,
            params string[] stringFields)
        {
            foreach (var field in expected)
            {
                if (Array.IndexOf(stringFields, field) >= 0)
                {
                    continue;
                }
                RequireNumericMember(actual, field, context);
            }
        }
    }
}
