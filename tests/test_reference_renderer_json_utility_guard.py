from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RENDERER = REPO / "reference-renderer" / "Assets" / "BodyRig"
SHIM = RENDERER / "BodyRigJsonUtility.cs"
DRIVER = RENDERER / "BodyRigMotorDriver.cs"
MOTOR_V1 = REPO / "contracts" / "bodyrig-motor-state-v1.schema.json"
MOTOR_V2 = REPO / "contracts" / "bodyrig-motor-state-v2.schema.json"
MOTOR_V3 = REPO / "contracts" / "bodyrig-motor-state-v3.schema.json"


def _array_fields(source: str, name: str) -> set[str]:
    match = re.search(
        rf"private static readonly string\[\] {re.escape(name)}\s*=\s*\{{(?P<body>.*?)\}};",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, name
    return set(re.findall(r'"([A-Za-z0-9_]+)"', match.group("body")))


def _contract(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _schema_required_by_action() -> dict[str, set[str]]:
    contract = _contract(MOTOR_V3)
    result: dict[str, set[str]] = {}
    for variant in contract["properties"]["locomotion"]["oneOf"]:
        action = variant["properties"]["action"]
        actions = [action["const"]] if "const" in action else list(action["enum"])
        required = set(variant["required"])
        for value in actions:
            result[value] = required
    return result


def _schema_posture_required() -> tuple[set[str], set[str]]:
    contract = _contract(MOTOR_V3)
    variants = contract["properties"]["posture"]["oneOf"]
    natural = next(
        item
        for item in variants
        if item["properties"].get("source", {}).get("const") == "modelrig-bodyprint-v1"
    )
    generic = next(item for item in variants if item is not natural)
    return set(generic["required"]), set(natural["required"])


def test_renderer_json_shim_preserves_all_jsonutility_surfaces_used_in_namespace() -> None:
    source = SHIM.read_text(encoding="utf-8")
    used: set[str] = set()
    for path in RENDERER.glob("*.cs"):
        if path == SHIM:
            continue
        used.update(re.findall(r"\bJsonUtility\.([A-Za-z0-9_]+)", path.read_text(encoding="utf-8")))

    assert used <= {"FromJson", "FromJsonOverwrite", "ToJson"}
    assert "public static T FromJson<T>(string json)" in source
    assert "public static object FromJson(string json, Type type)" in source
    assert "public static void FromJsonOverwrite(string json, object objectToOverwrite)" in source
    assert "public static string ToJson(object obj)" in source
    assert "public static string ToJson(object obj, bool prettyPrint)" in source
    assert "UnityEngine.JsonUtility.FromJson<T>(json)" in source
    assert "UnityEngine.JsonUtility.FromJson(json, type)" in source
    assert "UnityEngine.JsonUtility.FromJsonOverwrite(json, objectToOverwrite)" in source
    assert "UnityEngine.JsonUtility.ToJson(obj, prettyPrint)" in source


def test_shared_raw_guard_field_sets_follow_all_motor_schemas() -> None:
    source = SHIM.read_text(encoding="utf-8")
    contracts = [_contract(path) for path in (MOTOR_V1, MOTOR_V2, MOTOR_V3)]

    for name, schema_name in (
        ("MotionFields", "motion"),
        ("ExpressionFields", "expression"),
        ("GestureFields", "gesture"),
        ("GazeFields", "gaze"),
    ):
        expected = set(contracts[0]["properties"][schema_name]["required"])
        assert all(set(item["properties"][schema_name]["required"]) == expected for item in contracts)
        assert _array_fields(source, name) == expected

    speech = contracts[0]["properties"]["speech"]
    assert _array_fields(source, "SpeechAllowedFields") == set(speech["properties"])
    assert _array_fields(source, "SpeechRequiredFields") == set(speech["required"])

    observed = contracts[1]["properties"]["embodiment"]["properties"]["observed"]
    assert _array_fields(source, "ObservedEmbodimentFields") == set(observed["properties"])
    assert set(contracts[2]["properties"]["embodiment"]["properties"]["observed"]["properties"]) == set(
        observed["properties"]
    )


def test_v3_presence_guard_required_sets_are_derived_from_canonical_schema() -> None:
    source = SHIM.read_text(encoding="utf-8")
    required = _schema_required_by_action()
    generic_posture, natural_posture = _schema_posture_required()

    assert _array_fields(source, "WalkLocomotionFields") == required["walk"]
    assert _array_fields(source, "TurnLocomotionFields") == required["turn_left"]
    assert _array_fields(source, "TurnLocomotionFields") == required["turn_right"]
    assert _array_fields(source, "StopLocomotionFields") == required["stop"]
    assert _array_fields(source, "GenericPostureFields") == generic_posture
    assert _array_fields(source, "NaturalPostureFields") == natural_posture


def test_raw_guard_runs_for_v1_v2_v3_before_unity_erases_types() -> None:
    shim = SHIM.read_text(encoding="utf-8")
    driver = DRIVER.read_text(encoding="utf-8")

    assert "VersionPattern" in shim
    assert 'Groups["version"].Value' in shim
    generic = shim.index("public static T FromJson<T>(string json)")
    validate = shim.index("ValidateMotorStatePresenceAndTypes(json);", generic)
    deserialize = shim.index("UnityEngine.JsonUtility.FromJson<T>(json)", generic)
    assert validate < deserialize

    assert "namespace BodyRig.ReferenceRenderer" in shim
    assert "namespace BodyRig.ReferenceRenderer" in driver
    assert "JsonUtility.FromJson<MotorState>(json)" in driver


def test_shared_action_objects_fail_closed_before_deserialization() -> None:
    source = SHIM.read_text(encoding="utf-8")
    validate = source[
        source.index("private static void ValidateMotorStatePresenceAndTypes") :
        source.index("private static void ValidateRequiredExactFlatObject")
    ]

    assert "ValidateRequiredExactFlatObject(" in validate
    assert "MotionPropertyPattern" in validate
    assert "MotionObjectPattern" in validate
    for field in ("Expression", "Gesture", "Gaze"):
        assert f"{field}PropertyPattern" in validate
        assert f"{field}ObjectPattern" in validate
    assert "RequireExactFields(fields, expected, context);" in source
    assert "RequireNumericFields(body, expected, context, stringFields);" in source
    assert "must be a flat JSON object" in source
    assert "contains duplicate field" in source
    assert "is missing required field" in source


def test_duration_and_speech_preserve_integer_and_optional_type_presence() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert "JsonIntegerPattern" in source
    duration = source[source.index("private static void ValidateDuration") : source.index("private static void ValidateSpeech")]
    assert "DurationPropertyPattern.IsMatch(json)" in duration
    assert "JsonIntegerPattern" in duration
    assert "duration_ms requires an integer JSON token" in duration

    speech = source[source.index("private static void ValidateSpeech") : source.index("private static void ValidatePosture")]
    assert "SpeechPropertyPattern.IsMatch(json)" in speech
    assert "SpeechObjectPattern.Match(json)" in speech
    assert "RequireAllowedAndRequiredFields" in speech
    assert 'RequireStringField(body, "state", "speech")' in speech
    assert 'RequireIntegerField(body, "elapsed_ms", "speech")' in speech
    assert 'fields.Contains("viseme")' in speech
    assert 'RequireStringField(body, "viseme", "speech")' in speech
    assert 'fields.Contains("amplitude")' in speech
    assert 'RequireNumericField(body, "amplitude", "speech")' in speech


def test_embodiment_observed_cannot_collapse_to_empty_or_zero_defaults() -> None:
    source = SHIM.read_text(encoding="utf-8")
    embodiment = source[source.index("private static void ValidateEmbodiment") : source.index("private static void ValidateLocomotion")]

    assert "if (version < 2)" in embodiment
    assert "Motor State v1 may not carry embodiment" in embodiment
    assert 'ExtractObjectBody(json, "embodiment", "embodiment")' in embodiment
    assert "ObservedPropertyPattern.IsMatch(embodimentBody)" in embodiment
    assert "ObservedObjectPattern.Match(embodimentBody)" in embodiment
    assert "EmbodimentSourcePattern.IsMatch(outerWithoutObserved)" in embodiment
    assert "observedFields.Count == 0" in embodiment
    assert "requires at least one field" in embodiment
    assert "RequireAllowedFields(observedFields, ObservedEmbodimentFields" in embodiment
    assert 'RequireNumericField(observedBody, field, "embodiment.observed")' in embodiment


def test_v3_locomotion_and_posture_raw_guards_remain_strict() -> None:
    source = SHIM.read_text(encoding="utf-8")

    assert "LocomotionPropertyPattern.IsMatch(json)" in source
    assert "LocomotionObjectPattern.Match(json)" in source
    assert "PosturePropertyPattern.IsMatch(json)" in source
    assert "PostureObjectPattern.Match(json)" in source
    assert "PostureSourcePattern" in source
    assert 'fields.Contains("source")' in source
    assert 'version != 3 || id != "natural" || !PostureSourcePattern.IsMatch(body)' in source

    assert "JsonNumberPattern" in source
    assert 'RequireNumericFields(body, WalkLocomotionFields, action, "action");' in source
    assert 'RequireNumericFields(body, TurnLocomotionFields, action, "action");' in source
    assert 'RequireNumericFields(body, StopLocomotionFields, action, "action");' in source
    assert (
        'RequireNumericFields(body, NaturalPostureFields, "source-derived natural posture", "id", "source");'
        in source
    )
    assert 'RequireNumericFields(body, GenericPostureFields' in source
    assert "Regex.Escape(field)" in source
    assert "requires numeric field" in source


def test_legacy_natural_posture_stays_generic_without_source_marker() -> None:
    source = SHIM.read_text(encoding="utf-8")
    posture = source[
        source.index("private static void ValidatePosture") : source.index("private static void ValidateEmbodiment")
    ]

    source_branch = posture.index('if (fields.Contains("source"))')
    source_authority = posture.index("RequireExactFields(fields, NaturalPostureFields", source_branch)
    generic_authority = posture.index('RequireExactFields(fields, GenericPostureFields, $"posture {id}");')

    assert source_branch < source_authority < generic_authority
    assert 'version != 3 || id != "natural" || !PostureSourcePattern.IsMatch(body)' in posture
    assert 'RequireNumericFields(body, GenericPostureFields, $"posture {id}", "id");' in posture


def test_version_boundaries_reject_v1_embodiment_and_pre_v3_locomotion() -> None:
    source = SHIM.read_text(encoding="utf-8")
    embodiment = source[source.index("private static void ValidateEmbodiment") : source.index("private static void ValidateLocomotion")]
    locomotion = source[source.index("private static void ValidateLocomotion") : source.index("private static string ExtractObjectBody")]
    assert "if (version < 2)" in embodiment
    assert "if (version != 3)" in locomotion
    assert "Locomotion requires Motor State v3" in locomotion


def test_optional_action_objects_remain_optional() -> None:
    source = SHIM.read_text(encoding="utf-8")
    speech = source[source.index("private static void ValidateSpeech") : source.index("private static void ValidatePosture")]
    posture = source[source.index("private static void ValidatePosture") : source.index("private static void ValidateEmbodiment")]
    embodiment = source[source.index("private static void ValidateEmbodiment") : source.index("private static void ValidateLocomotion")]
    locomotion = source[source.index("private static void ValidateLocomotion") : source.index("private static string ExtractObjectBody")]
    for block, needle in (
        (speech, "SpeechPropertyPattern.IsMatch(json)"),
        (posture, "PosturePropertyPattern.IsMatch(json)"),
        (embodiment, "EmbodimentPropertyPattern.IsMatch(json)"),
        (locomotion, "LocomotionPropertyPattern.IsMatch(json)"),
    ):
        assert needle in block
        assert "return;" in block
