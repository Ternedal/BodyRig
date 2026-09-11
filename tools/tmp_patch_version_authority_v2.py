from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTILITY = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
DRIVER = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"
GUARD = ROOT / "tests" / "test_reference_renderer_json_utility_guard.py"
RAW_RANGES = ROOT / "tests" / "test_reference_renderer_raw_numeric_ranges.py"
WHITESPACE = ROOT / "tests" / "test_reference_renderer_json_whitespace_guard.py"
NEW_TEST = ROOT / "tests" / "test_reference_renderer_version_authority.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, got {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    UTILITY,
    """        internal static void ValidateMotorStateJson(string json)\n        {\n            ValidateMotorStatePresenceAndTypes(json, true);\n        }""",
    """        internal static int ValidateMotorStateJson(string json)\n        {\n            return ValidateMotorStatePresenceAndTypes(json, true);\n        }""",
)
replace_once(
    UTILITY,
    "        private static void ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)",
    "        private static int ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)",
)
for old in (
    """            if (string.IsNullOrEmpty(json))\n            {\n                if (requireMotorState)\n                {\n                    throw new ArgumentException(\"Motor State JSON is required\");\n                }\n                return;\n            }""",
    """            if (probeIndex >= json.Length || json[probeIndex] != '{')\n            {\n                if (requireMotorState)\n                {\n                    throw new ArgumentException(\"Motor State JSON root must be an object\");\n                }\n                return;\n            }""",
    """            if (!root.TryGetValue(\"type\", out var rawType))\n            {\n                if (requireMotorState)\n                {\n                    throw new ArgumentException(\"Motor State requires canonical type discriminator\");\n                }\n                return;\n            }""",
    """            if (!TryParseStringToken(rawType, out var type) || type != \"bodyrig-motor-state\")\n            {\n                if (requireMotorState)\n                {\n                    throw new ArgumentException(\"Motor State requires canonical type discriminator\");\n                }\n                return;\n            }""",
):
    replace_once(UTILITY, old, old.replace("                return;", "                return 0;"))
replace_once(
    UTILITY,
    """            ValidatePosture(root, version);\n            ValidateEmbodiment(root, version);\n            ValidateLocomotion(root, version);\n        }""",
    """            ValidatePosture(root, version);\n            ValidateEmbodiment(root, version);\n            ValidateLocomotion(root, version);\n            return version;\n        }""",
)

replace_once(DRIVER, "            public int version;", "            public int version { get; set; }")
replace_once(
    DRIVER,
    """            JsonUtility.ValidateMotorStateJson(json);\n            var next = JsonUtility.FromJson<MotorState>(json);\n            if (next == null || next.type != \"bodyrig-motor-state\" || (next.version != 1 && next.version != 2 && next.version != 3))\n            {\n                throw new ArgumentException(\"Unsupported BodyRig Motor State\", nameof(json));\n            }""",
    """            var validatedVersion = JsonUtility.ValidateMotorStateJson(json);\n            var next = JsonUtility.FromJson<MotorState>(json);\n            if (next == null || next.type != \"bodyrig-motor-state\")\n            {\n                throw new ArgumentException(\"Unsupported BodyRig Motor State\", nameof(json));\n            }\n            next.version = validatedVersion;""",
)

for path in (GUARD, RAW_RANGES, WHITESPACE):
    text = path.read_text(encoding="utf-8")
    if "private static void ValidateMotorStatePresenceAndTypes" not in text:
        raise SystemExit(f"{path}: missing validator signature assertion/slice")
    path.write_text(text.replace(
        "private static void ValidateMotorStatePresenceAndTypes",
        "private static int ValidateMotorStatePresenceAndTypes",
    ), encoding="utf-8")

replace_once(GUARD,
    '    assert "internal static void ValidateMotorStateJson(string json)" in shim',
    '    assert "internal static int ValidateMotorStateJson(string json)" in shim')
replace_once(GUARD,
    '        shim.index("internal static void ValidateMotorStateJson") :',
    '        shim.index("internal static int ValidateMotorStateJson") :')
replace_once(GUARD,
    '    assert "ValidateMotorStatePresenceAndTypes(json, true);" in dedicated',
    '    assert "return ValidateMotorStatePresenceAndTypes(json, true);" in dedicated')
replace_once(GUARD,
    '    assert driver.count("JsonUtility.ValidateMotorStateJson(json);") == 1',
    '    assert driver.count("var validatedVersion = JsonUtility.ValidateMotorStateJson(json);") == 1')
replace_once(GUARD,
    '    assert apply.index("JsonUtility.ValidateMotorStateJson(json);") < apply.index(',
    '    assert apply.index("var validatedVersion = JsonUtility.ValidateMotorStateJson(json);") < apply.index(')
replace_once(GUARD,
    '    assert "ValidateMotorStatePresenceAndTypes(json, true);" in source',
    '    assert "return ValidateMotorStatePresenceAndTypes(json, true);" in source')

NEW_TEST.write_text('''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\n\nREPO = Path(__file__).resolve().parents[1]\nUTILITY = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"\nDRIVER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigMotorDriver.cs"\nSCHEMAS = [\n    REPO / "contracts" / "bodyrig-motor-state-v1.schema.json",\n    REPO / "contracts" / "bodyrig-motor-state-v2.schema.json",\n    REPO / "contracts" / "bodyrig-motor-state-v3.schema.json",\n]\n\n\ndef test_dedicated_raw_validator_returns_schema_semantic_version() -> None:\n    constants = [json.loads(path.read_text(encoding="utf-8"))["properties"]["version"]["const"] for path in SCHEMAS]\n    assert constants == [1, 2, 3]\n\n    source = UTILITY.read_text(encoding="utf-8")\n    dedicated = source[source.index("internal static int ValidateMotorStateJson") : source.index("public static T FromJson<T>")]\n    assert "return ValidateMotorStatePresenceAndTypes(json, true);" in dedicated\n\n    validate = source[source.index("private static int ValidateMotorStatePresenceAndTypes") : source.index("private static int RequireMotorStateVersion")]\n    assert "var version = RequireMotorStateVersion(root);" in validate\n    assert "return version;" in validate\n    assert validate.count("return 0;") == 4\n\n\ndef test_unity_does_not_deserialize_version_authority() -> None:\n    source = DRIVER.read_text(encoding="utf-8")\n    motor = source[source.index("private sealed class MotorState") : source.index("public bool SourceObservedEmbodimentBound")]\n    assert "public int version { get; set; }" in motor\n    assert "public int version;" not in motor\n\n    apply = source[source.index("public void ApplyMotorJson") : source.index("private static void ValidatePosture")]\n    validate_call = "var validatedVersion = JsonUtility.ValidateMotorStateJson(json);"\n    deserialize_call = "var next = JsonUtility.FromJson<MotorState>(json);"\n    assign = "next.version = validatedVersion;"\n    assert validate_call in apply\n    assert deserialize_call in apply\n    assert assign in apply\n    assert apply.index(validate_call) < apply.index(deserialize_call) < apply.index(assign)\n    assert '(next.version != 1 && next.version != 2 && next.version != 3)' not in apply\n    assert apply.index(assign) < apply.index("if (next.version == 1 && next.embodiment != null)")\n    assert apply.index(assign) < apply.index("ValidatePosture(next.posture, next.version);")\n    assert apply.index(assign) < apply.index("if (next.version != 3) throw new ArgumentException")\n\n\ndef test_generic_jsonutility_surfaces_keep_optional_non_motor_behavior() -> None:\n    source = UTILITY.read_text(encoding="utf-8")\n    assert "private static int ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)" in source\n    assert source.count("ValidateMotorStatePresenceAndTypes(json);") == 3\n    assert "return 0;" in source\n''', encoding="utf-8")
