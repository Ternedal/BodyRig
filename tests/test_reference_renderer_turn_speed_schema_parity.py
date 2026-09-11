from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
SCHEMA = REPO / "contracts" / "bodyrig-motor-state-v3.schema.json"


def _turn_speed_schema() -> dict:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    variants = schema["properties"]["locomotion"]["oneOf"]
    turn = next(item for item in variants if item["properties"].get("action", {}).get("enum") == ["turn_left", "turn_right"])
    return turn["properties"]["turn_speed_degrees_per_second"]


def test_driver_preserves_schema_exclusive_positive_turn_speed_range() -> None:
    turn_speed = _turn_speed_schema()
    assert turn_speed["exclusiveMinimum"] == 0.0
    assert turn_speed["maximum"] == 720.0

    source = DRIVER.read_text(encoding="utf-8")
    locomotion = source[
        source.index("private static void ValidateLocomotion") :
        source.index("private static void ValidateObservedEmbodiment")
    ]
    assert "0.0001f" not in locomotion
    assert "ValidateExclusivePositiveRange(" in locomotion
    assert "locomotion.turn_speed_degrees_per_second" in locomotion
    assert "720.0f" in locomotion

    helper = source[
        source.index("private static void ValidateExclusivePositiveRange") :
        source.index("private static bool IsSupportedGestureId")
    ]
    assert "float.IsNaN(value)" in helper
    assert "float.IsInfinity(value)" in helper
    assert "value <= 0.0f" in helper
    assert "value > maximum" in helper


def test_raw_json_guard_keeps_original_token_exclusive_minimum_authority() -> None:
    source = SHIM.read_text(encoding="utf-8")
    locomotion = source[
        source.index("private static void ValidateLocomotion") :
        source.index("private static Dictionary<string, string> ParseObjectMembers")
    ]
    assert 'fields, "turn_speed_degrees_per_second", "locomotion", 0L, 720L, true' in locomotion


def test_schema_valid_positive_turn_speed_transport_underflow_is_normalized_after_raw_validation() -> None:
    turn_speed = _turn_speed_schema()
    assert turn_speed["exclusiveMinimum"] == 0.0
    assert turn_speed["maximum"] == 720.0

    driver = DRIVER.read_text(encoding="utf-8")
    apply = driver[
        driver.index("public void ApplyMotorJson") :
        driver.index("private static void ValidatePosture")
    ]
    raw_validation = "var validatedVersion = JsonUtility.ValidateMotorStateJson(json);"
    deserialize = "var next = JsonUtility.FromJson<MotorState>(json);"
    underflow_guard = 'next.locomotion.turn_speed_degrees_per_second == 0.0f'
    normalize = "next.locomotion.turn_speed_degrees_per_second = Mathf.Epsilon;"
    runtime_validation = "ValidateLocomotion(next.locomotion);"

    assert raw_validation in apply
    assert deserialize in apply
    assert '(next.locomotion.action == "turn_left" || next.locomotion.action == "turn_right")' in apply
    assert underflow_guard in apply
    assert normalize in apply
    assert apply.index(raw_validation) < apply.index(deserialize)
    assert apply.index(deserialize) < apply.index(underflow_guard) < apply.index(normalize)
    assert apply.index(normalize) < apply.index(runtime_validation)
    assert "0.0001f" not in apply[apply.index("if (next.locomotion != null)") : apply.index(runtime_validation) + len(runtime_validation)]

    shim = SHIM.read_text(encoding="utf-8")
    raw = shim[
        shim.index("private static void ValidateLocomotion") :
        shim.index("private static Dictionary<string, string> ParseObjectMembers")
    ]
    assert 'fields, "turn_speed_degrees_per_second", "locomotion", 0L, 720L, true' in raw
