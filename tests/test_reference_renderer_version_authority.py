from __future__ import annotations

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
    motor_state = source[
        source.index("private sealed class MotorState") :
        source.index("[SerializeField] private BodyRigAvatarLoader")
    ]
    assert "public int version { get; set; }" in motor_state
    assert "public int version;" not in motor_state

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
