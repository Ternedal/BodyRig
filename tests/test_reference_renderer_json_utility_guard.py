from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
RENDERER = REPO / "reference-renderer" / "Assets" / "BodyRig"
SHIM = RENDERER / "BodyRigJsonUtility.cs"
DRIVER = RENDERER / "BodyRigMotorDriver.cs"
MOTOR_V3 = REPO / "contracts" / "bodyrig-motor-state-v3.schema.json"


def _array_fields(source: str, name: str) -> set[str]:
    match = re.search(
        rf"private static readonly string\[\] {re.escape(name)}\s*=\s*\{{(?P<body>.*?)\}};",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, name
    return set(re.findall(r'"([A-Za-z0-9_]+)"', match.group("body")))


def _schema_required_by_action() -> dict[str, set[str]]:
    contract = json.loads(MOTOR_V3.read_text(encoding="utf-8"))
    result: dict[str, set[str]] = {}
    for variant in contract["properties"]["locomotion"]["oneOf"]:
        action = variant["properties"]["action"]
        actions = [action["const"]] if "const" in action else list(action["enum"])
        required = set(variant["required"])
        for value in actions:
            result[value] = required
    return result


def _schema_posture_required() -> tuple[set[str], set[str]]:
    contract = json.loads(MOTOR_V3.read_text(encoding="utf-8"))
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


def test_v3_presence_guard_rejects_missing_extra_duplicate_and_wrong_type_fields() -> None:
    source = SHIM.read_text(encoding="utf-8")

    assert "!MotorTypePattern.IsMatch(json)" in source
    assert "!VersionThreePattern.IsMatch(json)" in source
    assert "LocomotionPropertyPattern.IsMatch(json)" in source
    assert "LocomotionObjectPattern.Match(json)" in source
    assert "PosturePropertyPattern.IsMatch(json)" in source
    assert "PostureObjectPattern.Match(json)" in source
    assert "PostureSourcePattern" in source
    assert 'fields.Contains("source")' in source
    assert 'id != "natural" || !PostureSourcePattern.IsMatch(body)' in source
    assert "CollectUniqueFields" in source
    assert "actual.Count != expected.Length" in source
    assert "if (!actual.Contains(field))" in source
    assert "contains duplicate field" in source
    assert "is missing required field" in source

    # Unity can erase both absence and structural type mismatches into numeric
    # zero. The raw guard therefore also requires every non-string field to be
    # an actual JSON number token before deserialization. The source marker is
    # separately pinned to the exact BodyPrint authority string.
    assert "JsonNumberPattern" in source
    assert 'RequireNumericFields(body, WalkLocomotionFields, action, "action");' in source
    assert 'RequireNumericFields(body, TurnLocomotionFields, action, "action");' in source
    assert 'RequireNumericFields(body, StopLocomotionFields, action, "action");' in source
    assert (
        'RequireNumericFields(body, NaturalPostureFields, "source-derived natural posture", "id", "source");'
        in source
    )
    assert 'RequireNumericFields(body, GenericPostureFields' in source
    assert "Array.IndexOf(stringFields, field) >= 0" in source
    assert "Regex.Escape(field)" in source
    assert "requires numeric field" in source


def test_v3_presence_guard_keeps_legacy_natural_posture_generic_without_source_marker() -> None:
    source = SHIM.read_text(encoding="utf-8")
    posture = source[
        source.index("private static void ValidatePosture") : source.index("private static void ValidateLocomotion")
    ]

    assert 'if (fields.Contains("source"))' in posture
    assert 'RequireExactFields(fields, GenericPostureFields, $"posture {id}");' in posture
    assert 'old id literally named "natural" is not source authority' in posture


def test_v3_presence_guard_runs_before_unity_erases_missing_numeric_presence() -> None:
    shim = SHIM.read_text(encoding="utf-8")
    driver = DRIVER.read_text(encoding="utf-8")

    generic = shim.index("public static T FromJson<T>(string json)")
    validate = shim.index("ValidateMotorStateV3PresenceAndTypes(json);", generic)
    deserialize = shim.index("UnityEngine.JsonUtility.FromJson<T>(json)", generic)
    assert validate < deserialize

    # BodyRigMotorDriver deliberately keeps using the unqualified JsonUtility
    # symbol in the same namespace, so it resolves through this guard.
    assert "namespace BodyRig.ReferenceRenderer" in shim
    assert "namespace BodyRig.ReferenceRenderer" in driver
    assert "JsonUtility.FromJson<MotorState>(json)" in driver


def test_v3_optional_action_objects_remain_optional() -> None:
    source = SHIM.read_text(encoding="utf-8")
    validate = source[source.index("private static void ValidateMotorStateV3PresenceAndTypes") :]
    assert "ValidatePosture(json);" in validate
    assert "ValidateLocomotion(json);" in validate
    posture = source[
        source.index("private static void ValidatePosture") : source.index("private static void ValidateLocomotion")
    ]
    locomotion = source[
        source.index("private static void ValidateLocomotion") : source.index("private static HashSet<string>")
    ]
    assert "if (!PosturePropertyPattern.IsMatch(json))" in posture
    assert "return;" in posture
    assert "if (!LocomotionPropertyPattern.IsMatch(json))" in locomotion
    assert "return;" in locomotion
