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


def _contract(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _array_fields(source: str, name: str) -> set[str]:
    match = re.search(
        rf"private static readonly string\[\] {re.escape(name)}\s*=\s*\{{(?P<body>.*?)\}};",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, name
    return set(re.findall(r'"([A-Za-z0-9_]+)"', match.group("body")))


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
        item for item in variants
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
    assert used <= {"FromJson", "FromJsonOverwrite", "ToJson", "ValidateMotorStateJson", "ValidateRuntimeManifestJson"}
    generic = source.index("public static T FromJson<T>(string json)")
    assert source.index("ValidateMotorStatePresenceAndTypes(json);", generic) < source.index(
        "UnityEngine.JsonUtility.FromJson<T>(json)", generic
    )


def test_shared_raw_guard_field_sets_follow_all_motor_schemas() -> None:
    source = SHIM.read_text(encoding="utf-8")
    contracts = [_contract(path) for path in (MOTOR_V1, MOTOR_V2, MOTOR_V3)]
    for name, contract in zip(("RootV1Fields", "RootV2Fields", "RootV3Fields"), contracts, strict=True):
        assert _array_fields(source, name) == set(contract["properties"])
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


def test_raw_guard_uses_decoded_root_scoped_members_not_document_wide_regex_matches() -> None:
    source = SHIM.read_text(encoding="utf-8")
    validate = source[
        source.index("private static void ValidateMotorStatePresenceAndTypes") :
        source.index("private static string[] RootFieldsForVersion")
    ]
    assert 'var root = ParseObjectMembers(json, "root");' in validate
    assert 'root.TryGetValue("type", out var rawType)' in validate
    assert 'TryParseStringToken(rawType, out var type)' in validate
    assert 'type != "bodyrig-motor-state"' in validate
    assert 'root.TryGetValue("version", out var rawVersion)' in validate
    assert 'RequireAllowedFields(root, RootFieldsForVersion(version), $"root v{version}");' in validate
    assert 'ValidateRequiredExactObject(root, "motion"' in validate
    assert 'ValidateOptionalExactObject(root, "gaze"' in validate
    assert "MotorTypePattern" not in source
    assert "FlatObjectPattern" not in source
    assert "PropertyPattern" not in source


def test_root_field_sets_are_version_specific_and_fail_closed() -> None:
    source = SHIM.read_text(encoding="utf-8")
    chooser = source[source.index("private static string[] RootFieldsForVersion") : source.index("private static void ValidateRequiredExactObject")]
    assert "case 1: return RootV1Fields;" in chooser
    assert "case 2: return RootV2Fields;" in chooser
    assert "case 3: return RootV3Fields;" in chooser
    assert "RequireAllowedFields(root, RootFieldsForVersion(version)" in source
    assert "embodiment" not in _array_fields(source, "RootV1Fields")
    assert "locomotion" not in _array_fields(source, "RootV1Fields")
    assert "embodiment" in _array_fields(source, "RootV2Fields")
    assert "locomotion" not in _array_fields(source, "RootV2Fields")
    assert "locomotion" in _array_fields(source, "RootV3Fields")


def test_structural_scanner_is_string_aware_and_decodes_json_escapes() -> None:
    source = SHIM.read_text(encoding="utf-8")
    scanner = source[source.index("private static Dictionary<string, string> ParseObjectMembers") :]
    assert "ReadJsonString(json, ref index" in scanner
    assert "SkipJsonValue(json, ref index" in scanner
    assert "SkipComposite(json, ref index" in scanner
    assert "case 'u':" in scanner
    assert "HexValue" in scanner
    assert "contains duplicate field" in scanner
    assert "mismatched JSON delimiters" in scanner


def test_gaze_string_cannot_spoof_missing_strength_and_braces_remain_legal_string_content() -> None:
    source = SHIM.read_text(encoding="utf-8")
    exact = source[source.index("private static void ValidateExactObject") : source.index("private static void ValidateDuration")]
    parser = source[source.index("private static Dictionary<string, string> ParseObjectMembers") :]
    assert "var fields = ParseObjectMembers(raw, context);" in exact
    assert "RequireExactFields(fields, expected, context);" in exact
    assert "ReadJsonString(json, ref index, context);" in parser
    assert "current == '{'" in parser
    assert "current == '}'" in parser


def test_duration_speech_and_shared_string_types_fail_closed_before_unity() -> None:
    source = SHIM.read_text(encoding="utf-8")
    validate = source[source.index("private static void ValidateMotorStatePresenceAndTypes") :]
    assert 'RequireConstrainedStringMember(root, "body_id", "root", 1, 160, BodyIdPattern)' in validate
    assert 'RequireConstrainedStringMember(root, "utterance_id", "root", 1, 160, UtteranceIdPattern)' in validate
    assert 'ValidateDuration(root);' in validate
    assert 'RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L)' in validate
    speech = source[source.index("private static void ValidateSpeech") : source.index("private static void ValidatePosture")]
    assert 'RequireStringMember(fields, "state", "speech")' in speech
    assert 'RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L)' in speech
    assert 'RequireConstrainedStringMember(fields, "viseme", "speech", 1, 32, VisemePattern)' in speech
    assert 'RequireNumericRangeMember(fields, "amplitude", "speech", 0L, 1L)' in speech


def test_canonical_string_constraints_are_checked_after_json_escape_decoding() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[source.index("private static string RequireConstrainedStringMember") : source.index("private static void RequireNumericMember")]
    assert "var value = RequireStringMember(members, field, context);" in helper
    assert 'CountUnicodeScalars(value, context + "." + field)' in helper
    assert "scalarLength < minimumLength || scalarLength > maximumLength" in helper
    assert "value.Length < minimumLength" not in helper
    assert "Regex.IsMatch(value, pattern, RegexOptions.CultureInvariant)" in helper
    assert 'private const string BodyIdPattern = @"\\A[a-z0-9æøå_-]+\\z";' in source
    assert 'private const string LowerIdentifierPattern = @"\\A[a-z0-9_-]+\\z";' in source
    assert 'private const string UtteranceIdPattern = @"\\A[A-Za-z0-9._:-]+\\z";' in source
    assert 'private const string VisemePattern = @"\\A[A-Za-z0-9._-]+\\z";' in source
    validate = source[source.index("private static void ValidateMotorStatePresenceAndTypes") : source.index("private static string[] RootFieldsForVersion")]
    assert 'root, "expression", "emotion", "expression", 1, 64, LowerIdentifierPattern' in validate
    assert 'root, "gesture", "id", "gesture", 1, 80, LowerIdentifierPattern' in validate
    assert 'root, "gaze", "target", "gaze", 1, 127, null' in validate
    posture = source[source.index("private static void ValidatePosture") : source.index("private static void ValidateEmbodiment")]
    assert 'fields, "id", "posture", 1, 80, LowerIdentifierPattern' in posture
    assert "TryParseStringToken(raw, out var value)" in source
    assert "ReadJsonString(raw, ref index" in source


def test_schema_string_length_counts_unicode_scalars_and_rejects_unpaired_surrogates() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[source.index("private static int CountUnicodeScalars") : source.index("private static void RequireNumericMember")]
    assert "for (var index = 0; index < value.Length; index++)" in helper
    assert "char.IsHighSurrogate(current)" in helper
    assert "char.IsLowSurrogate(value[index + 1])" in helper
    assert "index++;" in helper
    assert "count++;" in helper
    assert "unpaired high surrogate" in helper
    assert "char.IsLowSurrogate(current)" in helper
    assert "unpaired low surrogate" in helper
    constrained = source[source.index("private static string RequireConstrainedStringMember") : source.index("private static int CountUnicodeScalars")]
    assert "var scalarLength = CountUnicodeScalars(value" in constrained
    assert "Unicode scalars" in constrained


def test_schema_string_limits_match_guard_constants_and_calls() -> None:
    source = SHIM.read_text(encoding="utf-8")
    v3 = _contract(MOTOR_V3)
    body = v3["properties"]["body_id"]
    utterance = v3["properties"]["utterance_id"]
    expression = v3["properties"]["expression"]["properties"]["emotion"]
    gesture = v3["properties"]["gesture"]["properties"]["id"]
    gaze = v3["properties"]["gaze"]["properties"]["target"]
    viseme = v3["properties"]["speech"]["properties"]["viseme"]
    assert (body["minLength"], body["maxLength"], body["pattern"]) == (1, 160, "^[a-z0-9æøå_-]+$")
    assert (utterance["minLength"], utterance["maxLength"], utterance["pattern"]) == (1, 160, "^[A-Za-z0-9._:-]+$")
    assert (expression["minLength"], expression["maxLength"], expression["pattern"]) == (1, 64, "^[a-z0-9_-]+$")
    assert (gesture["minLength"], gesture["maxLength"], gesture["pattern"]) == (1, 80, "^[a-z0-9_-]+$")
    assert (gaze["minLength"], gaze["maxLength"]) == (1, 127)
    assert (viseme["minLength"], viseme["maxLength"], viseme["pattern"]) == (1, 32, "^[A-Za-z0-9._-]+$")
    assert 'RequireConstrainedStringMember(root, "body_id", "root", 1, 160, BodyIdPattern)' in source
    assert 'RequireConstrainedStringMember(root, "utterance_id", "root", 1, 160, UtteranceIdPattern)' in source
    assert 'root, "expression", "emotion", "expression", 1, 64, LowerIdentifierPattern' in source
    assert 'root, "gesture", "id", "gesture", 1, 80, LowerIdentifierPattern' in source
    assert 'root, "gaze", "target", "gaze", 1, 127, null' in source
    assert 'fields, "id", "posture", 1, 80, LowerIdentifierPattern' in source
    assert 'RequireConstrainedStringMember(fields, "viseme", "speech", 1, 32, VisemePattern)' in source


def test_embodiment_observed_is_root_scoped_nonempty_known_and_numeric() -> None:
    source = SHIM.read_text(encoding="utf-8")
    embodiment = source[source.index("private static void ValidateEmbodiment") : source.index("private static void ValidateLocomotion")]
    assert 'root.TryGetValue("embodiment", out var raw)' in embodiment
    assert "if (version < 2)" in embodiment
    assert 'ParseObjectMembers(raw, "embodiment")' in embodiment
    assert 'new[] { "source", "observed" }' in embodiment
    assert 'RequireStringMember(embodiment, "source", "embodiment")' in embodiment
    assert 'ParseObjectMembers(embodiment["observed"], "embodiment.observed")' in embodiment
    assert "observed.Count == 0" in embodiment
    assert "RequireAllowedFields(observed, ObservedEmbodimentFields" in embodiment
    assert 'RequireNumericMember(observed, field, "embodiment.observed")' in embodiment


def test_v3_posture_and_locomotion_required_sets_remain_schema_derived() -> None:
    source = SHIM.read_text(encoding="utf-8")
    required = _schema_required_by_action()
    generic_posture, natural_posture = _schema_posture_required()
    assert _array_fields(source, "WalkLocomotionFields") == required["walk"]
    assert _array_fields(source, "TurnLocomotionFields") == required["turn_left"]
    assert _array_fields(source, "TurnLocomotionFields") == required["turn_right"]
    assert _array_fields(source, "StopLocomotionFields") == required["stop"]
    assert _array_fields(source, "GenericPostureFields") == generic_posture
    assert _array_fields(source, "NaturalPostureFields") == natural_posture
    posture = source[source.index("private static void ValidatePosture") : source.index("private static void ValidateEmbodiment")]
    locomotion = source[source.index("private static void ValidateLocomotion") : source.index("private static Dictionary<string, string> ParseObjectMembers")]
    assert 'version != 3 || id != "natural" || source != "modelrig-bodyprint-v1"' in posture
    assert "if (version != 3)" in locomotion


def test_driver_still_routes_motor_state_through_guard_and_preserves_post_merge_contracts() -> None:
    shim = SHIM.read_text(encoding="utf-8")
    driver = DRIVER.read_text(encoding="utf-8")
    assert "namespace BodyRig.ReferenceRenderer" in shim
    assert "namespace BodyRig.ReferenceRenderer" in driver
    assert "JsonUtility.FromJson<MotorState>(json)" in driver
    assert 'ValidateRange(next.duration_ms, 0.0f, 120000.0f, "duration_ms")' in driver
    assert "next.speech.elapsed_ms > 3600000" in driver
    assert "IsSupportedExpressionEmotion" in driver
    assert "IsSupportedSpeechViseme" in driver


def test_raw_integer_ranges_are_checked_before_unity_int_coercion() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[source.index("private static void RequireIntegerRangeToken") :]
    assert "RequireIntegerToken(raw, context);" in helper
    assert "CompareJsonNumberToInteger(raw, minimum) < 0" in helper
    assert "CompareJsonNumberToInteger(raw, maximum) > 0" in helper
    assert "long.TryParse(" not in helper
    assert "ArgumentOutOfRangeException" in helper

def test_motor_driver_requires_raw_discriminator_before_unity_deserialization() -> None:
    shim = SHIM.read_text(encoding="utf-8")
    driver = DRIVER.read_text(encoding="utf-8")

    assert "internal static int ValidateMotorStateJson(string json)" in shim
    dedicated = shim[
        shim.index("internal static int ValidateMotorStateJson") :
        shim.index("public static T FromJson<T>")
    ]
    assert "ValidateMotorStatePresenceAndTypes(json, true, out var validatedVersion);" in dedicated
    assert "return validatedVersion.Value;" in dedicated
    assert "bool requireMotorState = false" in shim
    assert "Motor State JSON root must be an object" in shim
    assert shim.count("Motor State requires canonical type discriminator") == 2

    assert driver.count("JsonUtility.ValidateMotorStateJson(json);") == 1
    apply = driver[
        driver.index("public void ApplyMotorJson") :
        driver.index("private static void ValidatePosture")
    ]
    assert apply.index("JsonUtility.ValidateMotorStateJson(json);") < apply.index(
        "JsonUtility.FromJson<MotorState>(json)"
    )
    assert apply.index("JsonUtility.FromJson<MotorState>(json)") < apply.index("_state = next;")


def test_generic_jsonutility_surfaces_remain_non_motor_compatible() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert "ValidateMotorStatePresenceAndTypes(json);" in source
    assert source.count("ValidateMotorStatePresenceAndTypes(json);") == 3
    assert "ValidateMotorStatePresenceAndTypes(json, true, out var validatedVersion);" in source
