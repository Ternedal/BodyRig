using System;
using System.Collections.Generic;
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
    /// State v3 action objects before deserialization can erase presence/type.
    /// </summary>
    internal static class JsonUtility
    {
        private const string JsonNumberPattern =
            "-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?";

        private static readonly Regex MotorTypePattern = new Regex(
            "\\\"type\\\"\\s*:\\s*\\\"bodyrig-motor-state\\\"",
            RegexOptions.CultureInvariant);

        private static readonly Regex VersionThreePattern = new Regex(
            "\\\"version\\\"\\s*:\\s*3(?:\\s*[,}])",
            RegexOptions.CultureInvariant);

        private static readonly Regex LocomotionPropertyPattern = new Regex(
            "\\\"locomotion\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex LocomotionObjectPattern = new Regex(
            "\\\"locomotion\\\"\\s*:\\s*\\{(?<body>[^{}]*)\\}",
            RegexOptions.CultureInvariant | RegexOptions.Singleline);

        private static readonly Regex PosturePropertyPattern = new Regex(
            "\\\"posture\\\"\\s*:",
            RegexOptions.CultureInvariant);

        private static readonly Regex PostureObjectPattern = new Regex(
            "\\\"posture\\\"\\s*:\\s*\\{(?<body>[^{}]*)\\}",
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

        private static void ValidateMotorStateV3PresenceAndTypes(string json)
        {
            if (string.IsNullOrWhiteSpace(json) ||
                !MotorTypePattern.IsMatch(json) ||
                !VersionThreePattern.IsMatch(json))
            {
                return;
            }

            ValidatePosture(json);
            ValidateLocomotion(json);
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

        private static HashSet<string> CollectUniqueFields(string body, string objectName)
        {
            var fields = new HashSet<string>(StringComparer.Ordinal);
            foreach (Match property in PropertyPattern.Matches(body))
            {
                var key = property.Groups["key"].Value;
                if (!fields.Add(key))
                {
                    throw new ArgumentException($"Motor State v3 {objectName} contains duplicate field: {key}");
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
                throw new ArgumentException(
                    $"Motor State v3 field set does not match {context}");
            }

            foreach (var field in expected)
            {
                if (!actual.Contains(field))
                {
                    throw new ArgumentException(
                        $"Motor State v3 {context} is missing required field: {field}");
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

                var pattern =
                    "\\\"" + Regex.Escape(field) + "\\\"\\s*:\\s*" +
                    JsonNumberPattern + "(?=\\s*(?:,|$))";
                if (!Regex.IsMatch(body, pattern, RegexOptions.CultureInvariant))
                {
                    throw new ArgumentException(
                        $"Motor State v3 {context} requires numeric field: {field}");
                }
            }
        }
    }
}
