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

    assert _array_fields(source, "WalkLocomotionFields") == required["walk"]
    assert _array_fields(source, "TurnLocomotionFields") == required["turn_left"]
    assert _array_fields(source, "TurnLocomotionFields") == required["turn_right"]
    assert _array_fields(source, "StopLocomotionFields") == required["stop"]


def test_v3_presence_guard_rejects_missing_extra_and_duplicate_locomotion_fields() -> None:
    source = SHIM.read_text(encoding="utf-8")

    assert "!MotorTypePattern.IsMatch(json)" in source
    assert "!VersionThreePattern.IsMatch(json)" in source
    assert "LocomotionPropertyPattern.IsMatch(json)" in source
    assert "LocomotionObjectPattern.Match(json)" in source
    assert "if (!fields.Add(key))" in source
    assert "actual.Count != expected.Length" in source
    assert "if (!actual.Contains(field))" in source
    assert "contains duplicate field" in source
    assert "is missing required field" in source


def test_v3_presence_guard_runs_before_unity_erases_missing_numeric_presence() -> None:
    shim = SHIM.read_text(encoding="utf-8")
    driver = DRIVER.read_text(encoding="utf-8")

    generic = shim.index("public static T FromJson<T>(string json)")
    validate = shim.index("ValidateMotorStateV3Presence(json);", generic)
    deserialize = shim.index("UnityEngine.JsonUtility.FromJson<T>(json)", generic)
    assert validate < deserialize

    # BodyRigMotorDriver deliberately keeps using the unqualified JsonUtility
    # symbol in the same namespace, so it resolves through this guard.
    assert "namespace BodyRig.ReferenceRenderer" in shim
    assert "namespace BodyRig.ReferenceRenderer" in driver
    assert "JsonUtility.FromJson<MotorState>(json)" in driver


def test_v3_without_locomotion_remains_valid_for_v1_cue_routed_through_v3() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert "if (!hasLocomotionProperty)" in source
    assert "return;" in source[source.index("if (!hasLocomotionProperty)") : source.index("var objectMatch")]
