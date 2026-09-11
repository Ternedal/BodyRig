from pathlib import Path

repo = Path(__file__).resolve().parents[2]
driver = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
contract_test = repo / "tests" / "test_reference_renderer_motor_v3_contract.py"
parity_test = repo / "tests" / "test_reference_renderer_turn_speed_schema_parity.py"

source = driver.read_text(encoding="utf-8")
if source.count("JsonUtility.ValidateMotorStateJson(json);") != 1:
    raise SystemExit("#362 discriminator gate is not present exactly once")
old_turn = '                    ValidateRange(locomotion.turn_speed_degrees_per_second, 0.0001f, 720.0f, "locomotion.turn_speed_degrees_per_second");\n'
new_turn = '''                    ValidateExclusivePositiveRange(
                        locomotion.turn_speed_degrees_per_second,
                        720.0f,
                        "locomotion.turn_speed_degrees_per_second");
'''
if source.count(old_turn) != 1:
    raise SystemExit(f"turn-speed validation anchor mismatch: {source.count(old_turn)}")
source = source.replace(old_turn, new_turn)

helper_anchor = '''        private static bool IsSupportedGestureId(string id)
'''
helper = '''        private static void ValidateExclusivePositiveRange(float value, float maximum, string field)
        {
            if (float.IsNaN(value) || float.IsInfinity(value) || value <= 0.0f || value > maximum)
            {
                throw new ArgumentOutOfRangeException(field, $"BodyRig motor value must be > 0 and <= {maximum}");
            }
        }

'''
if source.count(helper_anchor) != 1:
    raise SystemExit("gesture helper anchor mismatch")
if "private static void ValidateExclusivePositiveRange" in source:
    raise SystemExit("exclusive-positive helper already present")
source = source.replace(helper_anchor, helper + helper_anchor)
# Preserve the discriminator boundary after editing the same driver file.
if source.count("JsonUtility.ValidateMotorStateJson(json);") != 1:
    raise SystemExit("#362 discriminator gate was lost during turn-speed patch")
driver.write_text(source, encoding="utf-8")

contract = contract_test.read_text(encoding="utf-8")
old_assert = "    assert 'ValidateRange(locomotion.turn_speed_degrees_per_second, 0.0001f, 720.0f' in validation\n"
new_assert = '''    assert "ValidateExclusivePositiveRange(" in validation
    assert "locomotion.turn_speed_degrees_per_second" in validation
    assert "720.0f" in validation
    assert "0.0001f" not in validation
'''
if contract.count(old_assert) != 1:
    raise SystemExit("Motor v3 turn-speed test anchor mismatch")
contract_test.write_text(contract.replace(old_assert, new_assert), encoding="utf-8")

if parity_test.exists():
    raise SystemExit("turn-speed parity test already exists on reanchor base")
parity_test.write_text('''from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
SCHEMA = REPO / "contracts" / "bodyrig-motor-state-v3.schema.json"


def _turn_speed_schema() -> dict:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    variants = schema["properties"]["locomotion"]["oneOf"]
    turn = next(
        item
        for item in variants
        if item["properties"].get("action", {}).get("enum") == ["turn_left", "turn_right"]
    )
    return turn["properties"]["turn_speed_degrees_per_second"]


def test_driver_preserves_schema_exclusive_positive_turn_speed_range() -> None:
    turn_speed = _turn_speed_schema()
    assert turn_speed["exclusiveMinimum"] == 0.0
    assert turn_speed["maximum"] == 720.0

    source = DRIVER.read_text(encoding="utf-8")
    assert source.count("JsonUtility.ValidateMotorStateJson(json);") == 1
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
''', encoding="utf-8")
