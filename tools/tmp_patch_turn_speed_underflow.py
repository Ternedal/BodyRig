from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
TEST = ROOT / "tests" / "test_reference_renderer_turn_speed_schema_parity.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected 1 match, got {count}")
    return text.replace(old, new, 1)


driver = DRIVER.read_text(encoding="utf-8")
driver = replace_once(
    driver,
    '''            if (next.locomotion != null)\n            {\n                if (next.version != 3) throw new ArgumentException("Locomotion requires Motor State v3", nameof(json));\n                ValidateLocomotion(next.locomotion);\n            }\n''',
    '''            if (next.locomotion != null)\n            {\n                if (next.version != 3) throw new ArgumentException("Locomotion requires Motor State v3", nameof(json));\n                if ((next.locomotion.action == "turn_left" || next.locomotion.action == "turn_right") &&\n                    next.locomotion.turn_speed_degrees_per_second == 0.0f)\n                {\n                    // The raw validator already proved the original JSON value is\n                    // strictly > 0. A zero here can therefore only be float transport\n                    // underflow; preserve schema acceptance with the smallest positive\n                    // runtime representation before the ordinary runtime range check.\n                    next.locomotion.turn_speed_degrees_per_second = float.Epsilon;\n                }\n                ValidateLocomotion(next.locomotion);\n            }\n''',
    "locomotion validation block",
)
DRIVER.write_text(driver, encoding="utf-8")

test = TEST.read_text(encoding="utf-8")
test += '''\n\ndef test_schema_valid_positive_turn_speed_transport_underflow_is_normalized_after_raw_validation() -> None:\n    turn_speed = _turn_speed_schema()\n    assert turn_speed["exclusiveMinimum"] == 0.0\n    assert turn_speed["maximum"] == 720.0\n\n    driver = DRIVER.read_text(encoding="utf-8")\n    apply = driver[\n        driver.index("public void ApplyMotorJson") :\n        driver.index("private static void ValidatePosture")\n    ]\n    raw_validation = "var validatedVersion = JsonUtility.ValidateMotorStateJson(json);"\n    deserialize = "var next = JsonUtility.FromJson<MotorState>(json);"\n    underflow_guard = 'next.locomotion.turn_speed_degrees_per_second == 0.0f'\n    normalize = "next.locomotion.turn_speed_degrees_per_second = float.Epsilon;"\n    runtime_validation = "ValidateLocomotion(next.locomotion);"\n\n    assert raw_validation in apply\n    assert deserialize in apply\n    assert '(next.locomotion.action == "turn_left" || next.locomotion.action == "turn_right")' in apply\n    assert underflow_guard in apply\n    assert normalize in apply\n    assert apply.index(raw_validation) < apply.index(deserialize)\n    assert apply.index(deserialize) < apply.index(underflow_guard) < apply.index(normalize)\n    assert apply.index(normalize) < apply.index(runtime_validation)\n    assert "0.0001f" not in apply[apply.index("if (next.locomotion != null)") : apply.index(runtime_validation) + len(runtime_validation)]\n\n    shim = SHIM.read_text(encoding="utf-8")\n    raw = shim[\n        shim.index("private static void ValidateLocomotion") :\n        shim.index("private static Dictionary<string, string> ParseObjectMembers")\n    ]\n    assert 'fields, "turn_speed_degrees_per_second", "locomotion", 0L, 720L, true' in raw\n'''
TEST.write_text(test, encoding="utf-8")
