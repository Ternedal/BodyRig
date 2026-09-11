from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]


def test_motor_version_wire_field_matches_json_number_transport() -> None:
    constants = [
        json.loads(path.read_text(encoding="utf-8"))["properties"]["version"]["const"]
        for path in SCHEMAS
    ]
    assert constants == [1, 2, 3]

    source = DRIVER.read_text(encoding="utf-8")
    motor_state = source[
        source.index("private sealed class MotorState") :
        source.index("[SerializeField] private BodyRigAvatarLoader")
    ]
    assert "public float version;" in motor_state
    assert "public int version;" not in motor_state


def test_raw_semantic_version_remains_authoritative_after_float_wire_parse() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    apply = source[
        source.index("public void ApplyMotorJson") :
        source.index("private static void ValidatePosture")
    ]
    validate_call = "var validatedVersion = JsonUtility.ValidateMotorStateJson(json);"
    deserialize_call = "var next = JsonUtility.FromJson<MotorState>(json);"
    assign = "next.version = validatedVersion;"

    assert validate_call in apply
    assert deserialize_call in apply
    assert assign in apply
    assert apply.index(validate_call) < apply.index(deserialize_call) < apply.index(assign)
    assert "next.version != 1 && next.version != 2 && next.version != 3" not in apply
    assert "ValidatePosture(next.posture, validatedVersion);" in apply
    assert apply.index(assign) < apply.index("if (next.version == 1 && next.embodiment != null)")
    assert apply.index(assign) < apply.index("if (next.version < 3 && next.locomotion != null)")
    assert "public int LastMotorVersion => _state != null ? (int)_state.version : 0;" in source
