using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text.RegularExpressions;

namespace BodyRig.ReferenceRenderer
{
    /// <summary>
    /// Namespace-local shim around UnityEngine.JsonUtility.
    ///
    /// Unity's serializer maps missing or structurally incompatible numeric JSON
    /// members to CLR zero. Range validation alone therefore cannot distinguish
    /// a required field that was absent/malformed from one explicitly supplied
    /// as 0. Preserve JsonUtility everywhere else, but fail closed on raw Motor
    /// State action/evidence objects before deserialization can erase presence/type.
    /// </summary>
    internal static class JsonUtility
    {
        private const string JsonNumberPattern =
            "-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?";
        private const string JsonIntegerPattern =
            "-?(?:0|[1-9][0-9]*)";
        private const string JsonStringTokenPattern =
            "\\\"(?:\\\\.|[^\\\"\\\\])*\\\"";
        private const string FlatObjectItemPattern =
            "(?:" + JsonStringTokenPattern + "|[^{}\\\"])";
        private const string FlatObjectBodyPattern =
            FlatObjectItemPattern + "*";

        private static readonly Regex MotorTypePattern = new Regex(
            "\\\"type\\\"\\s*:\\s*\\\"bodyrig-motor-state\\\"",
            RegexOptions.CultureInvariant);

        private static readonly Regex VersionPattern = new Regex(
            "\\\"version\\\"\\s*:\\s*(?<version>[123])(?=\\s*[,}])",
            RegexOptions.CultureInvariant);

        // Retained as the exact v3 discriminator used by the historical guard.
        private static readonly Regex VersionThreePattern = new Regex(
            "\\\"version\\\"\\s*:\\s*3(?:\\s*[,}])",
            RegexOptions.CultureInvariant);

        private static readonly Regex MotionPropertyPattern = new Regex(
            "\\\"motion\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex MotionObjectPattern = new Regex(
            "\\\"motion\\\"\\s*:\\s*\\{(?<body>" + FlatObjectBodyPattern + ")\\}",
            RegexOptions.CultureInvariant | RegexOptions.Singleline);

        private static readonly Regex ExpressionPropertyPattern = new Regex(
            "\\\"expression\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex ExpressionObjectPattern = new Regex(
            "\\\"expression\\\"\\s*:\\s*\\{(?<body>" + FlatObjectBodyPattern + ")\\}",
            RegexOptions.CultureInvariant | RegexOptions.Singleline);

        private static readonly Regex GesturePropertyPattern = new Regex(
            "\\\"gesture\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex GestureObjectPattern = new Regex(
            "\\\"gesture\\\"\\s*:\\s*\\{(?<body>" + FlatObjectBodyPattern + ")\\}",
            RegexOptions.CultureInvariant | RegexOptions.Singleline);

        private static readonly Regex GazePropertyPattern = new Regex(
            "\\\"gaze\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex GazeObjectPattern = new Regex(
            "\\\"gaze\\\"\\s*:\\s*\\{(?<body>" + FlatObjectBodyPattern + ")\\}",
            RegexOptions.CultureInvariant | RegexOptions.Singleline);

        private static readonly Regex DurationPropertyPattern = new Regex(
            "\\\"duration_ms\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex SpeechPropertyPattern = new Regex(
            "\\\"speech\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex SpeechObjectPattern = new Regex(
            "\\\"speech\\\"\\s*:\\s*\\{(?<body>" + FlatObjectBodyPattern + ")\\}",
            RegexOptions.CultureInvariant | RegexOptions.Singleline);

        private static readonly Regex SpeechStatePattern = new Regex(
            "\\\"state\\\"\\s*:\\s*\\\"(?<state>start|update|stop)\\\"(?=\\s*(?:,|$))",
            RegexOptions.CultureInvariant);

        private static readonly Regex EmbodimentPropertyPattern = new Regex(
            "\\\"embodiment\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex EmbodimentObjectPattern = new Regex(
            "\\\"embodiment\\\"\\s*:\\s*\\{(?<before>[^{}]*?)\\\"observed\\\"\\s*:\\s*\\{(?<observed>[^{}]*)\\}(?<after>[^{}]*)\\}",
            RegexOptions.CultureInvariant | RegexOptions.Singleline);

        private static readonly Regex EmbodimentSourcePattern = new Regex(
            "\\\"source\\\"\\s*:\\s*\\\"modelrig-bodyprint-v1\\\"(?=\\s*(?:,|$))",
            RegexOptions.CultureInvariant);

        private static readonly Regex LocomotionPropertyPattern = new Regex(
            "\\\"locomotion\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex LocomotionObjectPattern = new Regex(
            "\\\"locomotion\\\"\\s*:\\s*\\{(?<body>" + FlatObjectBodyPattern + ")\\}",
            RegexOptions.CultureInvariant | RegexOptions.Singleline);

        private static readonly Regex PosturePropertyPattern = new Regex(
            "\\\"posture\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex PostureObjectPattern = new Regex(
            "\\\"posture\\\"\\s*:\\s*\\{(?<body>" + FlatObjectBodyPattern + ")\\}",
            RegexOptions.CultureInvariant | RegexOptions.Singleline);

        private static readonly Regex PropertyPattern = new Regex(
            "\\\"(?<key>[A-Za-z0-9_]+)\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex ActionPattern = new Regex(
            "\\\"action\\\"\\s*:\\s*\\\"(?<action>[a-z_]+)\\\"(?=\\s*(?:,|$))",
            RegexOptions.CultureInvariant);

        private static readonly Regex PostureIdPattern = new Regex(
            "\\\"id\\\"\\s*:\\s*\\\"(?<id>[a-z0-9_-]+)\\\"(?=\\s*(?:,|$))",
            RegexOptions.CultureInvariant);

        private static readonly Regex PostureSourcePattern = new Regex(
            "\\\"source\\\"\\s*:\\s*\\\"modelrig-bodyprint-v1\\\"(?=\\s*(?:,|$))",
            RegexOptions.CultureInvariant);

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

        private static readonly string[] SpeechRequiredFields =
        {
            "state",
            "elapsed_ms",
        };

        private static readonly string[] SpeechAllowedFields =
        {
            "state",
            "elapsed_ms",
            "viseme",
            "amplitude",
        };

        private static readonly string[] EmbodimentFields =
        {
            "source",
            "observed",
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

        public static T FromJson<T>(string json)
        {
            ValidateMotorStateV3PresenceAndTypes(json);
            return UnityEngine.JsonUtility.FromJson<T>(json);
        }

        public static object FromJson(string json, Type type)
        {
            ValidateMotorStateV3PresenceAndTypes(json);
            return UnityEngine.JsonUtility.FromJson(json, type);
        }

        public static void FromJsonOverwrite(string json, object objectToOverwrite)
        {
            ValidateMotorStateV3PresenceAndTypes(json);
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

        // Historical method name retained so every namespace-local JsonUtility
        // surface keeps one guard entrypoint. It now validates shared v1/v2/v3
        // Motor State fields before applying the v3-only posture/locomotion rules.
        private static void ValidateMotorStateV3PresenceAndTypes(string json)
        {
            if (string.IsNullOrWhiteSpace(json) || !MotorTypePattern.IsMatch(json))
            {
                return;
            }

            // Parse root member boundaries string-aware before any Unity
            // deserialization. This rejects duplicate root discriminators while
            // allowing braces/property-looking text inside legitimate strings.
            var rootFields = CollectRootFields(json);
            if (!rootFields.Contains("type"))
            {
                return;
            }

            var versionMatch = VersionPattern.Match(json);
            if (!versionMatch.Success)
            {
                throw new ArgumentException("BodyRig Motor State requires integer version 1, 2 or 3");
            }
            var version = int.Parse(versionMatch.Groups["version"].Value, CultureInfo.InvariantCulture);
            if (version == 3 && !VersionThreePattern.IsMatch(json))
            {
                throw new ArgumentException("BodyRig Motor State v3 version token is malformed");
            }

            ValidateMotion(json);
            ValidateExpression(json);
            ValidateGesture(json);
            ValidateGaze(json);
            ValidateDuration(json);
            ValidateSpeech(json);
            ValidateEmbodiment(json, version);

            if (version == 3)
            {
                ValidatePosture(json);
                ValidateLocomotion(json);
                return;
            }

            ValidateLegacyPosture(json);
            if (LocomotionPropertyPattern.IsMatch(json))
            {
                throw new ArgumentException("Motor State v1/v2 may not carry locomotion");
            }
        }

        private static void ValidateMotion(string json)
        {
            if (!MotionPropertyPattern.IsMatch(json))
            {
                throw new ArgumentException("BodyRig Motor State requires motion object");
            }
            var objectMatch = MotionObjectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException("Motor State motion must be a flat JSON object");
            }
            var body = objectMatch.Groups["body"].Value;
            var fields = CollectUniqueFields(body, "motion");
            RequireExactFields(fields, MotionFields, "motion");
            RequireNumericFields(body, MotionFields, "motion");
        }

        private static void ValidateExpression(string json)
        {
            if (!ExpressionPropertyPattern.IsMatch(json))
            {
                return;
            }
            var objectMatch = ExpressionObjectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException("Motor State expression must be a flat JSON object");
            }
            var body = objectMatch.Groups["body"].Value;
            var fields = CollectUniqueFields(body, "expression");
            RequireExactFields(fields, ExpressionFields, "expression");
            RequireStringField(body, "emotion", "expression");
            RequireNumericField(body, "intensity", "expression");
        }

        private static void ValidateGesture(string json)
        {
            if (!GesturePropertyPattern.IsMatch(json))
            {
                return;
            }
            var objectMatch = GestureObjectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException("Motor State gesture must be a flat JSON object");
            }
            var body = objectMatch.Groups["body"].Value;
            var fields = CollectUniqueFields(body, "gesture");
            RequireExactFields(fields, GestureFields, "gesture");
            RequireStringField(body, "id", "gesture");
            RequireNumericField(body, "amplitude", "gesture");
        }

        private static void ValidateGaze(string json)
        {
            if (!GazePropertyPattern.IsMatch(json))
            {
                return;
            }
            var objectMatch = GazeObjectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException("Motor State gaze must be a flat JSON object");
            }
            var body = objectMatch.Groups["body"].Value;
            var fields = CollectUniqueFields(body, "gaze");
            RequireExactFields(fields, GazeFields, "gaze");
            RequireStringField(body, "target", "gaze");
            RequireNumericField(body, "strength", "gaze");
        }

        private static void ValidateDuration(string json)
        {
            if (!DurationPropertyPattern.IsMatch(json))
            {
                return;
            }
            RequireIntegerProperty(json, "duration_ms", 0L, 120000L, "duration_ms");
        }

        private static void ValidateSpeech(string json)
        {
            if (!SpeechPropertyPattern.IsMatch(json))
            {
                return;
            }
            var objectMatch = SpeechObjectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException("Motor State speech must be a flat JSON object");
            }
            var body = objectMatch.Groups["body"].Value;
            var fields = CollectUniqueFields(body, "speech");
            RequireAllowedFields(fields, SpeechAllowedFields, "speech");
            RequireRequiredFields(fields, SpeechRequiredFields, "speech");
            if (!SpeechStatePattern.IsMatch(body))
            {
                throw new ArgumentException("Motor State speech requires start/update/stop string state");
            }
            RequireIntegerField(body, "elapsed_ms", 0L, 3600000L, "speech");
            if (fields.Contains("viseme"))
            {
                RequireStringField(body, "viseme", "speech");
            }
            if (fields.Contains("amplitude"))
            {
                RequireNumericField(body, "amplitude", "speech");
            }
        }

        private static void ValidateEmbodiment(string json, int version)
        {
            if (!EmbodimentPropertyPattern.IsMatch(json))
            {
                return;
            }
            if (version == 1)
            {
                throw new ArgumentException("Motor State v1 may not carry observed embodiment evidence");
            }

            var objectMatch = EmbodimentObjectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException("Motor State embodiment requires source plus flat observed object");
            }

            var outerBody =
                objectMatch.Groups["before"].Value +
                "\"observed\":0" +
                objectMatch.Groups["after"].Value;
            var outerFields = CollectUniqueFields(outerBody, "embodiment");
            RequireExactFields(outerFields, EmbodimentFields, "embodiment");
            if (!EmbodimentSourcePattern.IsMatch(outerBody))
            {
                throw new ArgumentException("Motor State embodiment requires modelrig-bodyprint-v1 source");
            }

            var observedBody = objectMatch.Groups["observed"].Value;
            var observedFields = CollectUniqueFields(observedBody, "embodiment.observed");
            if (observedFields.Count == 0)
            {
                throw new ArgumentException("Motor State embodiment.observed requires at least one field");
            }
            foreach (var field in observedFields)
            {
                if (Array.IndexOf(ObservedEmbodimentFields, field) < 0)
                {
                    throw new ArgumentException($"Motor State embodiment contains unknown observed field: {field}");
                }
                RequireNumericField(observedBody, field, "embodiment.observed");
            }
        }

        private static void ValidateLegacyPosture(string json)
        {
            if (!PosturePropertyPattern.IsMatch(json))
            {
                return;
            }
            var objectMatch = PostureObjectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException("Motor State v1/v2 posture must be a flat JSON object");
            }
            var body = objectMatch.Groups["body"].Value;
            var idMatch = PostureIdPattern.Match(body);
            if (!idMatch.Success)
            {
                throw new ArgumentException("Motor State v1/v2 posture requires a string id");
            }
            var fields = CollectUniqueFields(body, "posture");
            RequireExactFields(fields, GenericPostureFields, $"posture {idMatch.Groups["id"].Value}");
            RequireNumericFields(body, GenericPostureFields, "legacy posture", "id");
        }

        private static void ValidatePosture(string json)
        {
            if (!PosturePropertyPattern.IsMatch(json))
            {
                return;
            }

            var objectMatch = PostureObjectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException("Motor State v3 posture must be a flat JSON object");
            }

            var body = objectMatch.Groups["body"].Value;
            var idMatch = PostureIdPattern.Match(body);
            if (!idMatch.Success)
            {
                throw new ArgumentException("Motor State v3 posture requires a string id");
            }

            var fields = CollectUniqueFields(body, "posture");
            var id = idMatch.Groups["id"].Value;
            if (fields.Contains("source"))
            {
                if (id != "natural" || !PostureSourcePattern.IsMatch(body))
                {
                    throw new ArgumentException("Motor State v3 source-derived posture requires natural id and modelrig-bodyprint-v1 source");
                }
                RequireExactFields(fields, NaturalPostureFields, "source-derived natural posture");
                RequireNumericFields(body, NaturalPostureFields, "source-derived natural posture", "id", "source");
                return;
            }

            // Legacy/generic posture ids remain frozen. In particular, an old
            // id literally named "natural" is not source authority unless the
            // explicit source marker and signed fields are present.
            RequireExactFields(fields, GenericPostureFields, $"posture {id}");
            RequireNumericFields(body, GenericPostureFields, $"posture {id}", "id");
        }

        private static void ValidateLocomotion(string json)
        {
            if (!LocomotionPropertyPattern.IsMatch(json))
            {
                // Locomotion is optional in Motor State v3. A v1 cue routed
                // through v3 legitimately has no locomotion object.
                return;
            }

            var objectMatch = LocomotionObjectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException("Motor State v3 locomotion must be a flat JSON object");
            }

            var body = objectMatch.Groups["body"].Value;
            var actionMatch = ActionPattern.Match(body);
            if (!actionMatch.Success)
            {
                throw new ArgumentException("Motor State v3 locomotion requires a string action");
            }

            var fields = CollectUniqueFields(body, "locomotion");
            var action = actionMatch.Groups["action"].Value;
            switch (action)
            {
                case "walk":
                    RequireExactFields(fields, WalkLocomotionFields, action);
                    RequireNumericFields(body, WalkLocomotionFields, action, "action");
                    return;
                case "turn_left":
                case "turn_right":
                    RequireExactFields(fields, TurnLocomotionFields, action);
                    RequireNumericFields(body, TurnLocomotionFields, action, "action");
                    return;
                case "stop":
                    RequireExactFields(fields, StopLocomotionFields, action);
                    RequireNumericFields(body, StopLocomotionFields, action, "action");
                    return;
                default:
                    throw new ArgumentException($"Unsupported Motor State v3 locomotion action: {action}");
            }
        }

        private static HashSet<string> CollectRootFields(string json)
        {
            var trimmed = json.Trim();
            if (trimmed.Length < 2 || trimmed[0] != '{' || trimmed[trimmed.Length - 1] != '}')
            {
                throw new ArgumentException("Motor State must be one root JSON object");
            }
            return CollectUniqueFields(trimmed.Substring(1, trimmed.Length - 2), "root");
        }

        private static HashSet<string> CollectUniqueFields(string body, string objectName)
        {
            var fields = new HashSet<string>(StringComparer.Ordinal);
            var index = 0;
            while (true)
            {
                SkipWhitespace(body, ref index);
                if (index >= body.Length)
                {
                    return fields;
                }

                var key = ReadPropertyName(body, ref index, objectName);
                if (!fields.Add(key))
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
                SkipJsonValue(body, ref index, objectName);
                SkipWhitespace(body, ref index);

                if (index >= body.Length)
                {
                    return fields;
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

        private static string ReadPropertyName(string text, ref int index, string objectName)
        {
            if (index >= text.Length || text[index] != '"')
            {
                throw new ArgumentException($"Motor State {objectName} requires canonical string property names");
            }
            index++;
            var start = index;
            while (index < text.Length && text[index] != '"')
            {
                if (text[index] == '\\')
                {
                    throw new ArgumentException($"Motor State {objectName} may not escape property names");
                }
                index++;
            }
            if (index >= text.Length)
            {
                throw new ArgumentException($"Motor State {objectName} contains unterminated property name");
            }
            var key = text.Substring(start, index - start);
            index++;
            if (string.IsNullOrEmpty(key))
            {
                throw new ArgumentException($"Motor State {objectName} contains empty property name");
            }
            return key;
        }

        private static void SkipJsonValue(string text, ref int index, string objectName)
        {
            if (index >= text.Length)
            {
                throw new ArgumentException($"Motor State {objectName} contains missing JSON value");
            }
            if (text[index] == '"')
            {
                SkipJsonStringValue(text, ref index, objectName);
                return;
            }
            if (text[index] == '{' || text[index] == '[')
            {
                SkipCompositeJsonValue(text, ref index, objectName);
                return;
            }

            var start = index;
            while (index < text.Length && text[index] != ',')
            {
                index++;
            }
            if (string.IsNullOrWhiteSpace(text.Substring(start, index - start)))
            {
                throw new ArgumentException($"Motor State {objectName} contains empty JSON value");
            }
        }

        private static void SkipJsonStringValue(string text, ref int index, string objectName)
        {
            index++;
            while (index < text.Length)
            {
                if (text[index] == '\\')
                {
                    index += 2;
                    continue;
                }
                if (text[index] == '"')
                {
                    index++;
                    return;
                }
                index++;
            }
            throw new ArgumentException($"Motor State {objectName} contains unterminated JSON string");
        }

        private static void SkipCompositeJsonValue(string text, ref int index, string objectName)
        {
            var expected = new Stack<char>();
            while (index < text.Length)
            {
                var current = text[index];
                if (current == '"')
                {
                    SkipJsonStringValue(text, ref index, objectName);
                    continue;
                }
                if (current == '{')
                {
                    expected.Push('}');
                    index++;
                    continue;
                }
                if (current == '[')
                {
                    expected.Push(']');
                    index++;
                    continue;
                }
                if (current == '}' || current == ']')
                {
                    if (expected.Count == 0 || expected.Pop() != current)
                    {
                        throw new ArgumentException($"Motor State {objectName} contains mismatched JSON nesting");
                    }
                    index++;
                    if (expected.Count == 0)
                    {
                        return;
                    }
                    continue;
                }
                index++;
            }
            throw new ArgumentException($"Motor State {objectName} contains unterminated JSON composite value");
        }

        private static void SkipWhitespace(string text, ref int index)
        {
            while (index < text.Length && char.IsWhiteSpace(text[index]))
            {
                index++;
            }
        }

        private static void RequireExactFields(
            HashSet<string> actual,
            string[] expected,
            string context)
        {
            if (actual.Count != expected.Length)
            {
                throw new ArgumentException(
                    $"Motor State field set does not match {context}");
            }

            foreach (var field in expected)
            {
                if (!actual.Contains(field))
                {
                    throw new ArgumentException(
                        $"Motor State {context} is missing required field: {field}");
                }
            }
        }

        private static void RequireAllowedFields(
            HashSet<string> actual,
            string[] allowed,
            string context)
        {
            foreach (var field in actual)
            {
                if (Array.IndexOf(allowed, field) < 0)
                {
                    throw new ArgumentException($"Motor State {context} contains unknown field: {field}");
                }
            }
        }

        private static void RequireRequiredFields(
            HashSet<string> actual,
            string[] required,
            string context)
        {
            foreach (var field in required)
            {
                if (!actual.Contains(field))
                {
                    throw new ArgumentException($"Motor State {context} is missing required field: {field}");
                }
            }
        }

        private static void RequireStringField(string body, string field, string context)
        {
            var pattern =
                "\\\"" + Regex.Escape(field) + "\\\"\\s*:\\s*\\\"(?:\\\\.|[^\\\"\\\\])+\\\"" +
                "(?=\\s*(?:,|$))";
            if (!Regex.IsMatch(body, pattern, RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} requires string field: {field}");
            }
        }

        private static void RequireNumericField(string body, string field, string context)
        {
            var pattern =
                "\\\"" + Regex.Escape(field) + "\\\"\\s*:\\s*" +
                JsonNumberPattern + "(?=\\s*(?:,|$))";
            if (!Regex.IsMatch(body, pattern, RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} requires numeric field: {field}");
            }
        }

        private static void RequireNumericFields(
            string body,
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
                RequireNumericField(body, field, context);
            }
        }

        private static void RequireIntegerProperty(
            string json,
            string field,
            long minimum,
            long maximum,
            string context)
        {
            var pattern =
                "\\\"" + Regex.Escape(field) + "\\\"\\s*:\\s*(?<value>" +
                JsonIntegerPattern + ")(?=\\s*(?:,|}))";
            var match = Regex.Match(json, pattern, RegexOptions.CultureInvariant);
            if (!match.Success ||
                !long.TryParse(match.Groups["value"].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) ||
                value < minimum || value > maximum)
            {
                throw new ArgumentException($"Motor State {context} requires integer field in range: {field}");
            }
        }

        private static void RequireIntegerField(
            string body,
            string field,
            long minimum,
            long maximum,
            string context)
        {
            var pattern =
                "\\\"" + Regex.Escape(field) + "\\\"\\s*:\\s*(?<value>" +
                JsonIntegerPattern + ")(?=\\s*(?:,|$))";
            var match = Regex.Match(body, pattern, RegexOptions.CultureInvariant);
            if (!match.Success ||
                !long.TryParse(match.Groups["value"].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out var value) ||
                value < minimum || value > maximum)
            {
                throw new ArgumentException($"Motor State {context} requires integer field in range: {field}");
            }
        }
    }
}
