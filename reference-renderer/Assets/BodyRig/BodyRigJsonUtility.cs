using System;
using System.Collections.Generic;
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

        private static readonly Regex MotorTypePattern = new Regex(
            "\\\"type\\\"\\s*:\\s*\\\"bodyrig-motor-state\\\"",
            RegexOptions.CultureInvariant);

        private static readonly Regex VersionPattern = new Regex(
            "\\\"version\\\"\\s*:\\s*(?<version>[123])(?=\\s*[,}])",
            RegexOptions.CultureInvariant);

        private static readonly Regex MotionPropertyPattern = PropertyPresencePattern("motion");
        private static readonly Regex MotionObjectPattern = FlatObjectPattern("motion");
        private static readonly Regex ExpressionPropertyPattern = PropertyPresencePattern("expression");
        private static readonly Regex ExpressionObjectPattern = FlatObjectPattern("expression");
        private static readonly Regex GesturePropertyPattern = PropertyPresencePattern("gesture");
        private static readonly Regex GestureObjectPattern = FlatObjectPattern("gesture");
        private static readonly Regex GazePropertyPattern = PropertyPresencePattern("gaze");
        private static readonly Regex GazeObjectPattern = FlatObjectPattern("gaze");
        private static readonly Regex SpeechPropertyPattern = PropertyPresencePattern("speech");
        private static readonly Regex SpeechObjectPattern = FlatObjectPattern("speech");
        private static readonly Regex DurationPropertyPattern = PropertyPresencePattern("duration_ms");
        private static readonly Regex EmbodimentPropertyPattern = PropertyPresencePattern("embodiment");
        private static readonly Regex ObservedPropertyPattern = PropertyPresencePattern("observed");
        private static readonly Regex ObservedObjectPattern = FlatObjectPattern("observed");

        private static readonly Regex LocomotionPropertyPattern = PropertyPresencePattern("locomotion");
        private static readonly Regex LocomotionObjectPattern = FlatObjectPattern("locomotion");
        private static readonly Regex PosturePropertyPattern = PropertyPresencePattern("posture");
        private static readonly Regex PostureObjectPattern = FlatObjectPattern("posture");

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

        private static readonly Regex EmbodimentSourcePattern = new Regex(
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

        private static Regex PropertyPresencePattern(string name)
        {
            return new Regex(
                "\\\"" + Regex.Escape(name) + "\\\"\\s*:",
                RegexOptions.CultureInvariant);
        }

        private static Regex FlatObjectPattern(string name)
        {
            return new Regex(
                "\\\"" + Regex.Escape(name) + "\\\"\\s*:\\s*\\{(?<body>[^{}]*)\\}",
                RegexOptions.CultureInvariant | RegexOptions.Singleline);
        }

        private static void ValidateMotorStatePresenceAndTypes(string json)
        {
            if (string.IsNullOrWhiteSpace(json) || !MotorTypePattern.IsMatch(json))
            {
                return;
            }

            var versionMatch = VersionPattern.Match(json);
            if (!versionMatch.Success)
            {
                // Once a payload identifies itself as Motor State, do not let a
                // malformed version bypass the raw guard and rely on JsonUtility
                // coercion. The canonical contracts expose integer versions 1..3.
                throw new ArgumentException("Motor State requires integer version 1, 2, or 3");
            }
            var version = int.Parse(versionMatch.Groups["version"].Value);

            ValidateRequiredExactFlatObject(
                json, MotionPropertyPattern, MotionObjectPattern,
                MotionFields, "motion", Array.Empty<string>());
            ValidateOptionalExactFlatObject(
                json, ExpressionPropertyPattern, ExpressionObjectPattern,
                ExpressionFields, "expression", new[] { "emotion" });
            ValidateOptionalExactFlatObject(
                json, GesturePropertyPattern, GestureObjectPattern,
                GestureFields, "gesture", new[] { "id" });
            ValidateOptionalExactFlatObject(
                json, GazePropertyPattern, GazeObjectPattern,
                GazeFields, "gaze", new[] { "target" });
            ValidateDuration(json);
            ValidateSpeech(json);
            ValidatePosture(json, version);
            ValidateEmbodiment(json, version);
            ValidateLocomotion(json, version);
        }

        private static void ValidateRequiredExactFlatObject(
            string json,
            Regex propertyPattern,
            Regex objectPattern,
            string[] expected,
            string context,
            string[] stringFields)
        {
            if (!propertyPattern.IsMatch(json))
            {
                throw new ArgumentException($"Motor State requires {context} object");
            }
            ValidateExactFlatObject(json, objectPattern, expected, context, stringFields);
        }

        private static void ValidateOptionalExactFlatObject(
            string json,
            Regex propertyPattern,
            Regex objectPattern,
            string[] expected,
            string context,
            string[] stringFields)
        {
            if (!propertyPattern.IsMatch(json))
            {
                return;
            }
            ValidateExactFlatObject(json, objectPattern, expected, context, stringFields);
        }

        private static void ValidateExactFlatObject(
            string json,
            Regex objectPattern,
            string[] expected,
            string context,
            string[] stringFields)
        {
            var objectMatch = objectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException($"Motor State {context} must be a flat JSON object");
            }
            var body = objectMatch.Groups["body"].Value;
            var fields = CollectUniqueFields(body, context);
            RequireExactFields(fields, expected, context);
            RequireNumericFields(body, expected, context, stringFields);
        }

        private static void ValidateDuration(string json)
        {
            if (!DurationPropertyPattern.IsMatch(json))
            {
                return;
            }
            var pattern =
                "\\\"duration_ms\\\"\\s*:\\s*" + JsonIntegerPattern +
                "(?=\\s*(?:,|}))";
            if (!Regex.IsMatch(json, pattern, RegexOptions.CultureInvariant))
            {
                throw new ArgumentException("Motor State duration_ms requires an integer JSON token");
            }
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
            RequireAllowedAndRequiredFields(fields, SpeechAllowedFields, SpeechRequiredFields, "speech");
            RequireStringField(body, "state", "speech");
            RequireIntegerField(body, "elapsed_ms", "speech");
            if (fields.Contains("viseme")) RequireStringField(body, "viseme", "speech");
            if (fields.Contains("amplitude")) RequireNumericField(body, "amplitude", "speech");
        }

        private static void ValidatePosture(string json, int version)
        {
            if (!PosturePropertyPattern.IsMatch(json))
            {
                return;
            }

            var objectMatch = PostureObjectPattern.Match(json);
            if (!objectMatch.Success)
            {
                throw new ArgumentException("Motor State posture must be a flat JSON object");
            }

            var body = objectMatch.Groups["body"].Value;
            var idMatch = PostureIdPattern.Match(body);
            if (!idMatch.Success)
            {
                throw new ArgumentException("Motor State posture requires a string id");
            }

            var fields = CollectUniqueFields(body, "posture");
            var id = idMatch.Groups["id"].Value;
            if (fields.Contains("source"))
            {
                if (version != 3 || id != "natural" || !PostureSourcePattern.IsMatch(body))
                {
                    throw new ArgumentException("Motor State source-derived posture requires v3 natural id and modelrig-bodyprint-v1 source");
                }
                RequireExactFields(fields, NaturalPostureFields, "source-derived natural posture");
                RequireNumericFields(body, NaturalPostureFields, "source-derived natural posture", "id", "source");
                return;
            }

            RequireExactFields(fields, GenericPostureFields, $"posture {id}");
            RequireNumericFields(body, GenericPostureFields, $"posture {id}", "id");
        }

        private static void ValidateEmbodiment(string json, int version)
        {
            if (!EmbodimentPropertyPattern.IsMatch(json))
            {
                return;
            }
            if (version < 2)
            {
                throw new ArgumentException("Motor State v1 may not carry embodiment");
            }

            var embodimentBody = ExtractObjectBody(json, "embodiment", "embodiment");
            var observedMatch = ObservedObjectPattern.Match(embodimentBody);
            if (!ObservedPropertyPattern.IsMatch(embodimentBody) || !observedMatch.Success)
            {
                throw new ArgumentException("Motor State embodiment requires a flat observed object");
            }

            // Remove the nested observed object before validating the outer field
            // set. This keeps source/observed order irrelevant while still
            // rejecting duplicate/unknown outer authority fields.
            var outerWithoutObserved = embodimentBody.Remove(observedMatch.Index, observedMatch.Length);
            var outerFields = CollectUniqueFields(outerWithoutObserved, "embodiment");
            RequireExactFields(outerFields, new[] { "source" }, "embodiment outer fields");
            if (!EmbodimentSourcePattern.IsMatch(outerWithoutObserved))
            {
                throw new ArgumentException("Motor State embodiment requires modelrig-bodyprint-v1 source");
            }

            var observedBody = observedMatch.Groups["body"].Value;
            var observedFields = CollectUniqueFields(observedBody, "embodiment.observed");
            if (observedFields.Count == 0)
            {
                throw new ArgumentException("Motor State embodiment.observed requires at least one field");
            }
            RequireAllowedFields(observedFields, ObservedEmbodimentFields, "embodiment.observed");
            foreach (var field in observedFields)
            {
                RequireNumericField(observedBody, field, "embodiment.observed");
            }
        }

        private static void ValidateLocomotion(string json, int version)
        {
            if (!LocomotionPropertyPattern.IsMatch(json))
            {
                return;
            }
            if (version != 3)
            {
                throw new ArgumentException("Locomotion requires Motor State v3");
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

        private static string ExtractObjectBody(string json, string propertyName, string context)
        {
            var marker = Regex.Match(
                json,
                "\\\"" + Regex.Escape(propertyName) + "\\\"\\s*:",
                RegexOptions.CultureInvariant);
            if (!marker.Success)
            {
                throw new ArgumentException($"Motor State requires {context} object");
            }

            var index = marker.Index + marker.Length;
            while (index < json.Length && char.IsWhiteSpace(json[index])) index++;
            if (index >= json.Length || json[index] != '{')
            {
                throw new ArgumentException($"Motor State {context} must be a JSON object");
            }

            var start = ++index;
            var depth = 1;
            var inString = false;
            var escaped = false;
            for (; index < json.Length; index++)
            {
                var current = json[index];
                if (inString)
                {
                    if (escaped)
                    {
                        escaped = false;
                    }
                    else if (current == '\\')
                    {
                        escaped = true;
                    }
                    else if (current == '"')
                    {
                        inString = false;
                    }
                    continue;
                }

                if (current == '"')
                {
                    inString = true;
                }
                else if (current == '{')
                {
                    depth++;
                }
                else if (current == '}')
                {
                    depth--;
                    if (depth == 0)
                    {
                        return json.Substring(start, index - start);
                    }
                }
            }

            throw new ArgumentException($"Motor State {context} object is not closed");
        }

        private static HashSet<string> CollectUniqueFields(string body, string objectName)
        {
            var fields = new HashSet<string>(StringComparer.Ordinal);
            foreach (Match property in PropertyPattern.Matches(body))
            {
                var key = property.Groups["key"].Value;
                if (!fields.Add(key))
                {
                    throw new ArgumentException($"Motor State {objectName} contains duplicate field: {key}");
                }
            }
            return fields;
        }

        private static void RequireExactFields(
            HashSet<string> actual,
            string[] expected,
            string context)
        {
            if (actual.Count != expected.Length)
            {
                throw new ArgumentException($"Motor State field set does not match {context}");
            }
            foreach (var field in expected)
            {
                if (!actual.Contains(field))
                {
                    throw new ArgumentException($"Motor State {context} is missing required field: {field}");
                }
            }
        }

        private static void RequireAllowedAndRequiredFields(
            HashSet<string> actual,
            string[] allowed,
            string[] required,
            string context)
        {
            RequireAllowedFields(actual, allowed, context);
            foreach (var field in required)
            {
                if (!actual.Contains(field))
                {
                    throw new ArgumentException($"Motor State {context} is missing required field: {field}");
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
                    throw new ArgumentException($"Motor State {context} contains unsupported field: {field}");
                }
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

        private static void RequireIntegerField(string body, string field, string context)
        {
            var pattern =
                "\\\"" + Regex.Escape(field) + "\\\"\\s*:\\s*" +
                JsonIntegerPattern + "(?=\\s*(?:,|$))";
            if (!Regex.IsMatch(body, pattern, RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} requires integer field: {field}");
            }
        }

        private static void RequireStringField(string body, string field, string context)
        {
            var pattern =
                "\\\"" + Regex.Escape(field) +
                "\\\"\\s*:\\s*\\\"(?:\\\\.|[^\\\"\\\\])*\\\"(?=\\s*(?:,|$))";
            if (!Regex.IsMatch(body, pattern, RegexOptions.CultureInvariant))
            {
                throw new ArgumentException($"Motor State {context} requires string field: {field}");
            }
        }
    }
}