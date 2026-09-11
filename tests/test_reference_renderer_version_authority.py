from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
UTILITY = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
SCHEMAS = [
    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",
    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",
]


def test_dedicated_raw_validator_returns_schema_semantic_version() -> None:
    constants = [json.loads(path.read_text(encoding="utf-8"))["properties"]["version"]["const"] for path in SCHEMAS]
    assert constants == [1, 2, 3]

    source = UTILITY.read_text(encoding="utf-8")
    dedicated = source[source.index("internal static int ValidateMotorStateJson") : source.index("public static T FromJson<T>")]
    assert "return ValidateMotorStatePresenceAndTypes(json, true);" in dedicated

    validate = source[source.index("private static int ValidateMotorStatePresenceAndTypes") : source.index("private static int RequireMotorStateVersion")]
    assert "var version = RequireMotorStateVersion(root);" in validate
    assert "return version;" in validate
    assert validate.count("return 0;") == 4


def test_unity_does_not_deserialize_version_authority() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    motor = source[source.index("private sealed class MotorState") : source.index("public bool SourceObservedEmbodimentBound")]
    assert "public int version { get; set; }" in motor
    assert "public int version;" not in motor

    apply = source[source.index("public void ApplyMotorJson") : source.index("private static void ValidatePosture")]
    validate_call = "var validatedVersion = JsonUtility.ValidateMotorStateJson(json);"
    deserialize_call = "var next = JsonUtility.FromJson<MotorState>(json);"
    assign = "next.version = validatedVersion;"
    defense = "next.version != 1 && next.version != 2 && next.version != 3"
    assert validate_call in apply
    assert deserialize_call in apply
    assert assign in apply
    assert defense in apply
    assert apply.index(validate_call) < apply.index(deserialize_call) < apply.index(assign) < apply.index(defense)
    assert apply.index(assign) < apply.index("if (next.version == 1 && next.embodiment != null)")
    assert apply.index(assign) < apply.index("ValidatePosture(next.posture, next.version);")
    assert apply.index(assign) < apply.index("if (next.version != 3) throw new ArgumentException")


def test_generic_jsonutility_surfaces_keep_optional_non_motor_behavior() -> None:
    source = UTILITY.read_text(encoding="utf-8")
    assert "private static int ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)" in source
    assert source.count("ValidateMotorStatePresenceAndTypes(json);") == 3
    assert "return 0;" in source
