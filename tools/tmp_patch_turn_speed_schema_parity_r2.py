from pathlib import Path

path = Path("reference-renderer/Assets/BodyRig/BodyRigMotorDriver.cs")
source = path.read_text(encoding="utf-8")

old_call = '''                    ValidateRange(locomotion.turn_speed_degrees_per_second, 0.0001f, 720.0f, "locomotion.turn_speed_degrees_per_second");
'''
new_call = '''                    ValidateExclusivePositiveRange(
                        locomotion.turn_speed_degrees_per_second,
                        720.0f,
                        "locomotion.turn_speed_degrees_per_second");
'''
if source.count(old_call) != 1:
    raise SystemExit(f"turn-speed call anchor count={source.count(old_call)}")
source = source.replace(old_call, new_call, 1)

anchor = '''        private static void ValidateRange(float value, float minimum, float maximum, string field)
        {
            if (float.IsNaN(value) || float.IsInfinity(value) || value < minimum || value > maximum)
            {
                throw new ArgumentOutOfRangeException(field, $"BodyRig motor value must be in {minimum}..{maximum}");
            }
        }
'''
helper = '''
        private static void ValidateExclusivePositiveRange(float value, float maximum, string field)
        {
            if (float.IsNaN(value) || float.IsInfinity(value) || value <= 0.0f || value > maximum)
            {
                throw new ArgumentOutOfRangeException(field, $"BodyRig motor value must be > 0 and <= {maximum}");
            }
        }
'''
if source.count(anchor) != 1:
    raise SystemExit(f"ValidateRange anchor count={source.count(anchor)}")
source = source.replace(anchor, anchor + helper, 1)
path.write_text(source, encoding="utf-8")

test = Path("tests/test_reference_renderer_turn_speed_schema_parity.py")
test.write_text('''from __future__ import annotations

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
''', encoding="utf-8")

contract = Path("tests/test_reference_renderer_motor_v3_contract.py")
contract_source = contract.read_text(encoding="utf-8")
old_assert = '''    assert 'ValidateRange(locomotion.turn_speed_degrees_per_second, 0.0001f, 720.0f' in validation
'''
new_assert = '''    assert "ValidateExclusivePositiveRange(" in validation
    assert "locomotion.turn_speed_degrees_per_second" in validation
    assert "720.0f" in validation
    assert "0.0001f" not in validation
'''
if contract_source.count(old_assert) != 1:
    raise SystemExit(f"motor v3 turn-speed assertion anchor count={contract_source.count(old_assert)}")
contract.write_text(contract_source.replace(old_assert, new_assert, 1), encoding="utf-8")
