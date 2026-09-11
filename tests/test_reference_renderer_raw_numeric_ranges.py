from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
MOTOR_V1 = REPO / "contracts" / "bodyrig-motor-state-v1.schema.json"
MOTOR_V2 = REPO / "contracts" / "bodyrig-motor-state-v2.schema.json"
MOTOR_V3 = REPO / "contracts" / "bodyrig-motor-state-v3.schema.json"


def _contract(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _bounds(schema: dict) -> tuple[int | float, int | float, bool]:
    minimum = schema.get("minimum", schema.get("exclusiveMinimum"))
    maximum = schema["maximum"]
    return minimum, maximum, "exclusiveMinimum" in schema


def test_raw_numeric_guard_compares_json_decimal_text_before_unity_float_coercion() -> None:
    source = SHIM.read_text(encoding="utf-8")
    generic = source[source.index("public static T FromJson<T>(string json)") : source.index("public static object FromJson")]
    assert generic.index("ValidateMotorStatePresenceAndTypes(json);") < generic.index(
        "UnityEngine.JsonUtility.FromJson<T>(json)"
    )

    helper = source[
        source.index("private static void RequireNumericRangeToken") :
        source.index("private static void RequireIntegerToken")
    ]
    assert "RequireNumericToken(raw, context);" in helper
    assert "CompareJsonNumberToInteger(raw, minimum)" in helper
    assert "CompareJsonNumberToInteger(raw, maximum)" in helper
    assert "exclusiveMinimum && lowerComparison == 0" in helper
    assert "float.Parse" not in helper
    assert "double.Parse" not in helper
    assert "decimal.Parse" not in helper
    assert "float.TryParse" not in helper
    assert "double.TryParse" not in helper
    assert "decimal.TryParse" not in helper
    assert "CompareDecimalMagnitude" in helper
    assert "SaturatingAdd" in helper
    assert "SaturatingSubtract" in helper


def test_shared_v1_v2_v3_numeric_ranges_are_identical_and_guarded_raw() -> None:
    source = SHIM.read_text(encoding="utf-8")
    contracts = [_contract(path) for path in (MOTOR_V1, MOTOR_V2, MOTOR_V3)]
    expected = {
        ("motion", "energy"): (0.0, 1.0, False),
        ("motion", "head_motion"): (0.0, 1.0, False),
        ("expression", "intensity"): (0.0, 1.0, False),
        ("gesture", "amplitude"): (0.0, 1.0, False),
        ("gaze", "strength"): (0.0, 1.0, False),
        ("posture", "intensity"): (0.0, 1.0, False),
        ("speech", "amplitude"): (0.0, 1.0, False),
    }
    for (object_name, field), bounds in expected.items():
        for contract in contracts:
            property_schema = contract["properties"][object_name]
            if object_name == "posture" and "oneOf" in property_schema:
                property_schema = property_schema["oneOf"][0]
            assert _bounds(property_schema["properties"][field]) == bounds

    validate = source[
        source.index("private static void ValidateMotorStatePresenceAndTypes") :
        source.index("private static string[] RootFieldsForVersion")
    ]
    assert 'ValidateObjectNumericRange(root, "motion", "energy", "motion", 0L, 1L);' in validate
    assert 'ValidateObjectNumericRange(root, "motion", "head_motion", "motion", 0L, 1L);' in validate
    assert 'ValidateObjectNumericRange(root, "expression", "intensity", "expression", 0L, 1L);' in validate
    assert 'ValidateObjectNumericRange(root, "gesture", "amplitude", "gesture", 0L, 1L);' in validate
    assert 'ValidateObjectNumericRange(root, "gaze", "strength", "gaze", 0L, 1L);' in validate

    speech = source[source.index("private static void ValidateSpeech") : source.index("private static void ValidatePosture")]
    assert 'RequireNumericRangeMember(fields, "amplitude", "speech", 0L, 1L);' in speech
    posture = source[source.index("private static void ValidatePosture") : source.index("private static void ValidateEmbodiment")]
    assert 'RequireNumericRangeMember(fields, "intensity", "posture", 0L, 1L);' in posture


def test_v3_source_posture_ranges_match_schema_before_float_coercion() -> None:
    source = SHIM.read_text(encoding="utf-8")
    v3 = _contract(MOTOR_V3)
    natural = next(
        item for item in v3["properties"]["posture"]["oneOf"]
        if item["properties"].get("source", {}).get("const") == "modelrig-bodyprint-v1"
    )
    expected = {
        "torso_forward_lean_degrees": (-90.0, 90.0, False),
        "torso_right_lean_degrees": (-90.0, 90.0, False),
        "shoulder_roll_degrees": (-90.0, 90.0, False),
        "hip_roll_degrees": (-90.0, 90.0, False),
        "head_forward_offset_to_height": (-1.0, 1.0, False),
        "head_right_offset_to_height": (-1.0, 1.0, False),
    }
    posture = source[source.index("private static void ValidatePosture") : source.index("private static void ValidateEmbodiment")]
    for field, bounds in expected.items():
        assert _bounds(natural["properties"][field]) == bounds
        minimum, maximum, _ = bounds
        assert (
            f'RequireNumericRangeMember(fields, "{field}", "posture", '
            f'{int(minimum)}L, {int(maximum)}L);'
        ) in posture


def test_v2_v3_observed_embodiment_range_switch_covers_every_schema_field() -> None:
    source = SHIM.read_text(encoding="utf-8")
    v2 = _contract(MOTOR_V2)
    v3 = _contract(MOTOR_V3)
    observed_v2 = v2["properties"]["embodiment"]["properties"]["observed"]["properties"]
    observed_v3 = v3["properties"]["embodiment"]["properties"]["observed"]["properties"]
    assert observed_v2 == observed_v3

    helper = source[
        source.index("private static void ValidateObservedEmbodimentNumericRange") :
        source.index("private static void ValidateLocomotion")
    ]
    cases = set(re.findall(r'case "([A-Za-z0-9_]+)":', helper))
    assert cases == set(observed_v2)
    assert 'RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 1L);' in helper
    assert 'RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 300L);' in helper
    assert 'RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 90L);' in helper
    assert 'RequireNumericRangeMember(observed, field, "embodiment.observed", -90L, 90L);' in helper
    assert 'RequireNumericRangeMember(observed, field, "embodiment.observed", -1L, 1L);' in helper
    assert 'RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 2L);' in helper
    assert 'RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 720L);' in helper
    assert 'RequireNumericRangeMember(observed, field, "embodiment.observed", 0L, 120L);' in helper
    assert "has no canonical numeric range for field" in helper


def test_v3_locomotion_raw_ranges_match_schema_including_exclusive_turn_minimum() -> None:
    source = SHIM.read_text(encoding="utf-8")
    v3 = _contract(MOTOR_V3)
    variants = v3["properties"]["locomotion"]["oneOf"]
    by_action: dict[str, dict] = {}
    for variant in variants:
        action = variant["properties"]["action"]
        actions = [action["const"]] if "const" in action else list(action["enum"])
        for value in actions:
            by_action[value] = variant

    assert _bounds(by_action["walk"]["properties"]["effort"]) == (0.0, 1.0, False)
    assert _bounds(by_action["walk"]["properties"]["cadence_spm"]) == (30.0, 240.0, False)
    assert _bounds(by_action["walk"]["properties"]["stride_length_to_height"]) == (0.0, 2.0, False)
    assert _bounds(by_action["turn_left"]["properties"]["turn_speed_degrees_per_second"]) == (0.0, 720.0, True)

    locomotion = source[
        source.index("private static void ValidateLocomotion") :
        source.index("private static Dictionary<string, string> ParseObjectMembers")
    ]
    assert 'RequireNumericRangeMember(fields, "cadence_spm", "locomotion", 30L, 240L);' in locomotion
    assert 'RequireNumericRangeMember(fields, "stride_length_to_height", "locomotion", 0L, 2L);' in locomotion
    assert 'fields, "turn_speed_degrees_per_second", "locomotion", 0L, 720L, true' in locomotion
    assert locomotion.count('RequireNumericRangeMember(fields, "effort", "locomotion", 0L, 1L);') == 3
    assert locomotion.count('RequireNumericRangeMember(fields, "transition_intensity", "locomotion", 0L, 1L);') == 3


def test_integer_range_guard_remains_separate_from_raw_number_range_guard() -> None:
    source = SHIM.read_text(encoding="utf-8")
    assert 'RequireIntegerRangeToken(raw, "duration_ms", 0L, 120000L)' in source
    assert 'RequireIntegerRangeMember(fields, "elapsed_ms", "speech", 0L, 3600000L)' in source
    integer = source[source.index("private static void RequireIntegerRangeToken") :]
    assert "long.TryParse(" in integer
    assert "value < minimum || value > maximum" in integer
