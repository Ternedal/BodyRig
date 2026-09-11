from pathlib import Path

repo = Path.cwd()
shim = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
driver = repo / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"

source = shim.read_text(encoding="utf-8")
old_entry = '''        internal static void ValidateMotorStateJson(string json)
        {
            ValidateMotorStatePresenceAndTypes(json, true);
        }
'''
new_entry = '''        internal static int ValidateMotorStateJson(string json)
        {
            ValidateMotorStatePresenceAndTypes(json, true, out var validatedVersion);
            if (!validatedVersion.HasValue)
            {
                throw new ArgumentException("Motor State semantic version is required");
            }
            return validatedVersion.Value;
        }
'''
if source.count(old_entry) != 1:
    raise SystemExit(f"ValidateMotorStateJson anchor count={source.count(old_entry)}")
source = source.replace(old_entry, new_entry, 1)

old_open = '''        private static void ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)
        {
            if (string.IsNullOrEmpty(json))
'''
new_open = '''        private static void ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)
        {
            ValidateMotorStatePresenceAndTypes(json, requireMotorState, out _);
        }

        private static void ValidateMotorStatePresenceAndTypes(
            string json,
            bool requireMotorState,
            out int? validatedVersion)
        {
            validatedVersion = null;
            if (string.IsNullOrEmpty(json))
'''
if source.count(old_open) != 1:
    raise SystemExit(f"ValidateMotorStatePresenceAndTypes anchor count={source.count(old_open)}")
source = source.replace(old_open, new_open, 1)

old_end = '''            ValidatePosture(root, version);
            ValidateEmbodiment(root, version);
            ValidateLocomotion(root, version);
        }

        private static int RequireMotorStateVersion(Dictionary<string, string> root)
'''
new_end = '''            ValidatePosture(root, version);
            ValidateEmbodiment(root, version);
            ValidateLocomotion(root, version);
            validatedVersion = version;
        }

        private static int RequireMotorStateVersion(Dictionary<string, string> root)
'''
if source.count(old_end) != 1:
    raise SystemExit(f"validated version publication anchor count={source.count(old_end)}")
source = source.replace(old_end, new_end, 1)
shim.write_text(source, encoding="utf-8")

driver_source = driver.read_text(encoding="utf-8")
old_driver = '''            JsonUtility.ValidateMotorStateJson(json);
            var next = JsonUtility.FromJson<MotorState>(json);
            if (next == null || next.type != "bodyrig-motor-state" || (next.version != 1 && next.version != 2 && next.version != 3))
            {
                throw new ArgumentException("Unsupported BodyRig Motor State", nameof(json));
            }
            if (string.IsNullOrWhiteSpace(next.body_id) || string.IsNullOrWhiteSpace(next.utterance_id) || next.motion == null)
'''
new_driver = '''            var validatedVersion = JsonUtility.ValidateMotorStateJson(json);
            var next = JsonUtility.FromJson<MotorState>(json);
            if (next == null || next.type != "bodyrig-motor-state")
            {
                throw new ArgumentException("Unsupported BodyRig Motor State", nameof(json));
            }
            next.version = validatedVersion;
            if (string.IsNullOrWhiteSpace(next.body_id) || string.IsNullOrWhiteSpace(next.utterance_id) || next.motion == null)
'''
if driver_source.count(old_driver) != 1:
    raise SystemExit(f"driver version authority anchor count={driver_source.count(old_driver)}")
driver_source = driver_source.replace(old_driver, new_driver, 1)
driver.write_text(driver_source, encoding="utf-8")

guard = repo / "tests" / "test_reference_renderer_json_utility_guard.py"
guard_source = guard.read_text(encoding="utf-8")
old_guard = '''    assert "internal static void ValidateMotorStateJson(string json)" in shim
    dedicated = shim[
        shim.index("internal static void ValidateMotorStateJson") :
        shim.index("public static T FromJson<T>")
    ]
    assert "ValidateMotorStatePresenceAndTypes(json, true);" in dedicated
'''
new_guard = '''    assert "internal static int ValidateMotorStateJson(string json)" in shim
    dedicated = shim[
        shim.index("internal static int ValidateMotorStateJson") :
        shim.index("public static T FromJson<T>")
    ]
    assert "ValidateMotorStatePresenceAndTypes(json, true, out var validatedVersion);" in dedicated
    assert "return validatedVersion.Value;" in dedicated
'''
if guard_source.count(old_guard) != 1:
    raise SystemExit(f"dedicated guard test anchor count={guard_source.count(old_guard)}")
guard_source = guard_source.replace(old_guard, new_guard, 1)
old_generic = '''    assert "ValidateMotorStatePresenceAndTypes(json, true);" in source
'''
new_generic = '''    assert "ValidateMotorStatePresenceAndTypes(json, true, out var validatedVersion);" in source
'''
if guard_source.count(old_generic) != 1:
    raise SystemExit(f"generic guard test anchor count={guard_source.count(old_generic)}")
guard_source = guard_source.replace(old_generic, new_generic, 1)
guard.write_text(guard_source, encoding="utf-8")

v2_test = repo / "tests" / "test_reference_renderer_motor_v2_contract.py"
v2_source = v2_test.read_text(encoding="utf-8")
old_v2 = '''    assert "next.version != 1 && next.version != 2 && next.version != 3" in source
'''
new_v2 = '''    assert "next.version = validatedVersion;" in source
    assert "next.version != 1 && next.version != 2 && next.version != 3" not in source
'''
if v2_source.count(old_v2) != 1:
    raise SystemExit(f"v2 version contract anchor count={v2_source.count(old_v2)}")
v2_source = v2_source.replace(old_v2, new_v2, 1)
v2_test.write_text(v2_source, encoding="utf-8")

test = repo / "tests" / "test_reference_renderer_version_authority.py"
if test.exists():
    raise SystemExit("version authority regression already exists")
test.write_text('''from __future__ import annotations

from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
DRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"


def test_dedicated_raw_validator_returns_only_fully_validated_semantic_version() -> None:
    source = SHIM.read_text(encoding="utf-8")
    entry = source[
        source.index("internal static int ValidateMotorStateJson") :
        source.index("public static T FromJson<T>")
    ]
    assert "ValidateMotorStatePresenceAndTypes(json, true, out var validatedVersion);" in entry
    assert "return validatedVersion.Value;" in entry

    raw = source[
        source.index("private static void ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)") :
        source.index("private static int RequireMotorStateVersion")
    ]
    assert "out int? validatedVersion" in raw
    assert "validatedVersion = null;" in raw
    assert "var version = RequireMotorStateVersion(root);" in raw
    assert "validatedVersion = version;" in raw
    assert raw.index("var version = RequireMotorStateVersion(root);") < raw.index("ValidatePosture(root, version);")
    assert raw.index("ValidatePosture(root, version);") < raw.index("ValidateEmbodiment(root, version);")
    assert raw.index("ValidateEmbodiment(root, version);") < raw.index("ValidateLocomotion(root, version);")
    assert raw.index("ValidateLocomotion(root, version);") < raw.index("validatedVersion = version;")


def test_generic_json_utility_paths_keep_optional_motor_state_guard_behavior() -> None:
    source = SHIM.read_text(encoding="utf-8")
    wrappers = source[
        source.index("public static T FromJson<T>") :
        source.index("private static void ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)")
    ]
    assert wrappers.count("ValidateMotorStatePresenceAndTypes(json);") == 3
    assert "out var validatedVersion" not in wrappers


def test_driver_uses_raw_semantic_version_after_unity_deserialization() -> None:
    source = DRIVER.read_text(encoding="utf-8")
    apply = source[
        source.index("public void ApplyMotorJson") :
        source.index("private static void ValidatePosture")
    ]
    raw_call = "var validatedVersion = JsonUtility.ValidateMotorStateJson(json);"
    unity_call = "var next = JsonUtility.FromJson<MotorState>(json);"
    assign = "next.version = validatedVersion;"
    assert raw_call in apply
    assert unity_call in apply
    assert assign in apply
    assert apply.index(raw_call) < apply.index(unity_call) < apply.index(assign)
    assert "next.version != 1" not in apply
    assert apply.index(assign) < apply.index("if (next.version == 1 && next.embodiment != null)")
    assert apply.index(assign) < apply.index("if (next.version < 3 && next.locomotion != null)")
    assert apply.index(assign) < apply.index("ValidatePosture(next.posture, next.version);")
''', encoding="utf-8")
