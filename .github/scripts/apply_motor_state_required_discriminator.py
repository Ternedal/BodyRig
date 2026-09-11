from pathlib import Path

repo = Path(__file__).resolve().parents[2]
shim = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
driver = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
test = repo / "tests" / "test_reference_renderer_json_utility_guard.py"

source = shim.read_text(encoding="utf-8")
anchor = '''        public static T FromJson<T>(string json)
        {
            ValidateMotorStatePresenceAndTypes(json);
            return UnityEngine.JsonUtility.FromJson<T>(json);
        }
'''
replacement = '''        internal static void ValidateMotorStateJson(string json)
        {
            ValidateMotorStatePresenceAndTypes(json, true);
        }

''' + anchor
if source.count(anchor) != 1:
    raise SystemExit(f"expected one generic FromJson anchor, found {source.count(anchor)}")
source = source.replace(anchor, replacement)

old_signature = '        private static void ValidateMotorStatePresenceAndTypes(string json)\n'
new_signature = '        private static void ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)\n'
if source.count(old_signature) != 1:
    raise SystemExit("validator signature anchor mismatch")
source = source.replace(old_signature, new_signature)

old_empty = '''            if (string.IsNullOrEmpty(json))
            {
                return;
            }
'''
new_empty = '''            if (string.IsNullOrEmpty(json))
            {
                if (requireMotorState)
                {
                    throw new ArgumentException("Motor State JSON is required");
                }
                return;
            }
'''
if source.count(old_empty) != 1:
    raise SystemExit("empty-json guard anchor mismatch")
source = source.replace(old_empty, new_empty)

old_object = '''            if (probeIndex >= json.Length || json[probeIndex] != '{')
            {
                return;
            }
'''
new_object = '''            if (probeIndex >= json.Length || json[probeIndex] != '{')
            {
                if (requireMotorState)
                {
                    throw new ArgumentException("Motor State JSON root must be an object");
                }
                return;
            }
'''
if source.count(old_object) != 1:
    raise SystemExit("object-root guard anchor mismatch")
source = source.replace(old_object, new_object)

old_type = '''            if (!root.TryGetValue("type", out var rawType))
            {
                return;
            }
            if (!TryParseStringToken(rawType, out var type) || type != "bodyrig-motor-state")
            {
                return;
            }
'''
new_type = '''            if (!root.TryGetValue("type", out var rawType))
            {
                if (requireMotorState)
                {
                    throw new ArgumentException("Motor State requires canonical type discriminator");
                }
                return;
            }
            if (!TryParseStringToken(rawType, out var type) || type != "bodyrig-motor-state")
            {
                if (requireMotorState)
                {
                    throw new ArgumentException("Motor State requires canonical type discriminator");
                }
                return;
            }
'''
if source.count(old_type) != 1:
    raise SystemExit("type discriminator guard anchor mismatch")
source = source.replace(old_type, new_type)
shim.write_text(source, encoding="utf-8")

driver_source = driver.read_text(encoding="utf-8")
old_driver = '            var next = JsonUtility.FromJson<MotorState>(json);\n'
new_driver = '            JsonUtility.ValidateMotorStateJson(json);\n            var next = JsonUtility.FromJson<MotorState>(json);\n'
if driver_source.count(old_driver) != 1:
    raise SystemExit("MotorState deserialize anchor mismatch")
driver.write_text(driver_source.replace(old_driver, new_driver), encoding="utf-8")

test_source = test.read_text(encoding="utf-8")
old_allowlist = '    assert used <= {"FromJson", "FromJsonOverwrite", "ToJson"}\n'
new_allowlist = '    assert used <= {"FromJson", "FromJsonOverwrite", "ToJson", "ValidateMotorStateJson"}\n'
if test_source.count(old_allowlist) != 1:
    raise SystemExit("JsonUtility surface allowlist anchor mismatch")
test_source = test_source.replace(old_allowlist, new_allowlist)

addition = r'''

def test_motor_driver_requires_raw_discriminator_before_unity_deserialization() -> None:
    shim = SHIM.read_text(encoding="utf-8")
    driver = DRIVER.read_text(encoding="utf-8")

    assert "internal static void ValidateMotorStateJson(string json)" in shim
    dedicated = shim[
        shim.index("internal static void ValidateMotorStateJson") :
        shim.index("public static T FromJson<T>")
    ]
    assert "ValidateMotorStatePresenceAndTypes(json, true);" in dedicated
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
    assert "ValidateMotorStatePresenceAndTypes(json, true);" in source
'''
if "test_motor_driver_requires_raw_discriminator_before_unity_deserialization" in test_source:
    raise SystemExit("discriminator regression tests already present")
test.write_text((test_source.rstrip() + addition).rstrip() + "\n", encoding="utf-8")
