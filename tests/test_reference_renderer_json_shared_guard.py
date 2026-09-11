from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RENDERER = REPO / "reference-renderer" / "Assets" / "BodyRig"
SHIM = RENDERER / "BodyRigJsonUtility.cs"
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]


def _array_fields(source: str, name: str) -> set[str]:
    match = re.search(
        rf"private static readonly string\[\] {re.escape(name)}\s*=\s*\{{(?P<body>.*?)\}};",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, name
    return set(re.findall(r'"([A-Za-z0-9_]+)"', match.group("body")))


def _schemas() -> list[dict]:
    return [json.loads(path.read_text(encoding="utf-8")) for path in SCHEMAS]


def test_shared_motor_state_shapes_are_stable_across_v1_v2_v3() -> None:
    schemas = _schemas()
    for name in ("motion", "expression", "gesture", "gaze", "speech"):
        first = schemas[0]["properties"][name]
        for schema in schemas[1:]:
            assert schema["properties"][name] == first, name
    assert schemas[0]["properties"]["duration_ms"] == schemas[1]["properties"]["duration_ms"]
    assert schemas[1]["properties"]["duration_ms"] == schemas[2]["properties"]["duration_ms"]


def test_raw_guard_arrays_follow_shared_schema_authority() -> None:
    source = SHIM.read_text(encoding="utf-8")
    schema = _schemas()[0]

    assert _array_fields(source, "MotionFields") == set(schema["properties"]["motion"]["required"])
    assert _array_fields(source, "ExpressionFields") == set(schema["properties"]["expression"]["required"])
    assert _array_fields(source, "GestureFields") == set(schema["properties"]["gesture"]["required"])
    assert _array_fields(source, "GazeFields") == set(schema["properties"]["gaze"]["required"])
    assert _array_fields(source, "SpeechRequiredFields") == set(schema["properties"]["speech"]["required"])
    assert _array_fields(source, "SpeechAllowedFields") == set(schema["properties"]["speech"]["properties"])

    observed = set(_schemas()[1]["properties"]["embodiment"]["properties"]["observed"]["properties"])
    assert _array_fields(source, "ObservedEmbodimentFields") == observed


def test_shared_raw_guard_runs_before_every_unity_deserialization_surface() -> None:
    source = SHIM.read_text(encoding="utf-8")
    for signature, deserialize in (
        ("public static T FromJson<T>(string json)", "UnityEngine.JsonUtility.FromJson<T>(json)"),
        ("public static object FromJson(string json, Type type)", "UnityEngine.JsonUtility.FromJson(json, type)"),
        ("public static void FromJsonOverwrite(string json, object objectToOverwrite)", "UnityEngine.JsonUtility.FromJsonOverwrite(json, objectToOverwrite)"),
    ):
        start = source.index(signature)
        guard = source.index("ValidateMotorStateV3PresenceAndTypes(json);", start)
        unity = source.index(deserialize, start)
        assert start < guard < unity


def test_shared_raw_guard_validates_all_non_locomotion_numeric_surfaces() -> None:
    source = SHIM.read_text(encoding="utf-8")
    validate = source[
        source.index("private static void ValidateMotorStateV3PresenceAndTypes") :
        source.index("private static void ValidateMotion")
    ]

    assert "VersionPattern.Match(json)" in validate
    assert "ValidateMotion(json);" in validate
    assert "ValidateExpression(json);" in validate
    assert "ValidateGesture(json);" in validate
    assert "ValidateGaze(json);" in validate
    assert "ValidateDuration(json);" in validate
    assert "ValidateSpeech(json);" in validate
    assert "ValidateEmbodiment(json, version);" in validate
    assert "if (version == 3)" in validate
    assert "ValidatePosture(json);" in validate
    assert "ValidateLocomotion(json);" in validate
    assert "ValidateLegacyPosture(json);" in validate

    for method in ("ValidateMotion", "ValidateExpression", "ValidateGesture", "ValidateGaze"):
        assert f"private static void {method}" in source
    assert "RequireNumericFields" in source
    assert "RequireStringField" in source


def test_duration_and_speech_integer_tokens_and_ranges_are_checked_before_deserialization() -> None:
    source = SHIM.read_text(encoding="utf-8")

    duration = source[source.index("private static void ValidateDuration") : source.index("private static void ValidateSpeech")]
    speech = source[source.index("private static void ValidateSpeech") : source.index("private static void ValidateEmbodiment")]

    assert "RequireIntegerProperty" in duration
    assert '"duration_ms"' in duration
    assert "120000L" in duration
    assert "RequireIntegerField" in speech
    assert '"elapsed_ms"' in speech
    assert "3600000L" in speech
    assert 'fields.Contains("amplitude")' in speech
    assert 'RequireNumericField(body, "amplitude"' in speech
    assert 'fields.Contains("viseme")' in speech
    assert 'RequireStringField(body, "viseme"' in speech
    assert "JsonIntegerPattern" in source
    assert "long.TryParse" in source


def test_embodiment_observed_raw_guard_requires_nonempty_known_numeric_fields() -> None:
    source = SHIM.read_text(encoding="utf-8")
    embodiment = source[
        source.index("private static void ValidateEmbodiment") :
        source.index("private static void ValidateLegacyPosture")
    ]

    assert "version == 1" in embodiment
    assert "EmbodimentObjectPattern.Match(json)" in embodiment
    assert 'objectMatch.Groups["observed"].Value' in embodiment
    assert "CollectUniqueFields" in embodiment
    assert "observedFields.Count == 0" in embodiment
    assert "ObservedEmbodimentFields" in embodiment
    assert "Array.IndexOf(ObservedEmbodimentFields, field) < 0" in embodiment
    assert "contains unknown observed field" in embodiment
    assert "RequireNumericField(observedBody, field" in embodiment
    assert "RequireExactFields(outerFields, EmbodimentFields" in embodiment
    assert "EmbodimentSourcePattern.IsMatch(outerBody)" in embodiment


def test_optional_action_objects_are_optional_but_exact_when_present() -> None:
    source = SHIM.read_text(encoding="utf-8")

    expression = source[source.index("private static void ValidateExpression") : source.index("private static void ValidateGesture")]
    gesture = source[source.index("private static void ValidateGesture") : source.index("private static void ValidateGaze")]
    gaze = source[source.index("private static void ValidateGaze") : source.index("private static void ValidateDuration")]
    speech = source[source.index("private static void ValidateSpeech") : source.index("private static void ValidateEmbodiment")]

    assert "if (!ExpressionPropertyPattern.IsMatch(json))" in expression
    assert "if (!GesturePropertyPattern.IsMatch(json))" in gesture
    assert "if (!GazePropertyPattern.IsMatch(json))" in gaze
    assert "if (!SpeechPropertyPattern.IsMatch(json))" in speech
    assert "RequireExactFields(fields, ExpressionFields" in expression
    assert "RequireExactFields(fields, GestureFields" in gesture
    assert "RequireExactFields(fields, GazeFields" in gaze
    assert "RequireAllowedFields(fields, SpeechAllowedFields" in speech
    assert "RequireRequiredFields(fields, SpeechRequiredFields" in speech


def test_legacy_posture_and_v3_specific_guards_remain_separate() -> None:
    source = SHIM.read_text(encoding="utf-8")
    legacy = source[source.index("private static void ValidateLegacyPosture") : source.index("private static void ValidatePosture")]
    v3 = source[source.index("private static void ValidatePosture") : source.index("private static void ValidateLocomotion")]

    assert "GenericPostureFields" in legacy
    assert "NaturalPostureFields" not in legacy
    assert 'fields.Contains("source")' in v3
    assert "NaturalPostureFields" in v3
    assert "PostureSourcePattern" in v3



def test_raw_guard_is_string_aware_and_rejects_duplicate_root_members() -> None:
    source = SHIM.read_text(encoding="utf-8")
    guard = source[
        source.index("private static void ValidateMotorStateV3PresenceAndTypes") :
        source.index("private static void ValidateMotion")
    ]
    collector = source[
        source.index("private static HashSet<string> CollectRootFields") :
        source.index("private static void RequireExactFields")
    ]

    assert "JsonStringTokenPattern" in source
    assert "FlatObjectBodyPattern" in source
    assert "FlatObjectBodyPattern" in source[source.index("GazeObjectPattern") : source.index("DurationPropertyPattern")]
    assert "CollectRootFields(json)" in guard
    assert "ReadPropertyName" in collector
    assert "SkipJsonStringValue" in collector
    assert "SkipCompositeJsonValue" in collector
    assert "PropertyPattern.Matches(body)" not in collector
    assert "contains duplicate field" in collector
    assert "may not escape property names" in collector
