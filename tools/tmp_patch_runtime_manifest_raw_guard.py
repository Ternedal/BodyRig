from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHIM = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
LOADER = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigAvatarLoader.cs"
JSON_GUARD_TEST = ROOT / "tests" / "test_reference_renderer_json_utility_guard.py"
RUNTIME_TEST = ROOT / "tests" / "test_reference_renderer_runtime_manifest_guard.py"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}: {old!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    SHIM,
    '        private const string VisemePattern = @"\\A[A-Za-z0-9._-]+\\z";\n\n        private static readonly string[] RootV1Fields =\n',
    '        private const string VisemePattern = @"\\A[A-Za-z0-9._-]+\\z";\n'
    '        private const string Sha256Pattern = @"\\A[0-9a-f]{64}\\z";\n\n'
    '        private static readonly string[] RuntimeManifestFields =\n'
    '        {\n'
    '            "format",\n'
    '            "version",\n'
    '            "body_id",\n'
    '            "body_name",\n'
    '            "package_sha256",\n'
    '            "avatar",\n'
    '            "avatar_sha256",\n'
    '            "bodyprint",\n'
    '            "bodyprint_sha256",\n'
    '            "payloads",\n'
    '        };\n\n'
    '        private static readonly string[] RuntimeManifestPayloads =\n'
    '        {\n'
    '            "avatar.vrm",\n'
    '            "bodyprint.json",\n'
    '            "provenance.json",\n'
    '            "thumbnail.png",\n'
    '            "motions/idle.vrma",\n'
    '            "motions/walk.vrma",\n'
    '            "motions/talk.vrma",\n'
    '            "motions/gesture_01.vrma",\n'
    '            "motions/gesture_02.vrma",\n'
    '            "motions/gesture_03.vrma",\n'
    '        };\n\n'
    '        private static readonly string[] RootV1Fields =\n',
)

replace_once(
    SHIM,
    '        internal static int ValidateMotorStateJson(string json)\n',
    '''        internal static int ValidateRuntimeManifestJson(string json)\n        {\n            if (string.IsNullOrEmpty(json))\n            {\n                throw new ArgumentException("Runtime manifest JSON is required");\n            }\n\n            var root = ParseObjectMembers(json, "runtime manifest");\n            RequireExactFields(root, RuntimeManifestFields, "runtime manifest");\n\n            var format = RequireStringMember(root, "format", "runtime manifest");\n            if (format != "bodyrig-runtime-assets")\n            {\n                throw new ArgumentException("Runtime manifest requires bodyrig-runtime-assets format");\n            }\n\n            if (!root.TryGetValue("version", out var rawVersion))\n            {\n                throw new ArgumentException("Runtime manifest requires numeric version 1");\n            }\n            RequireNumericToken(rawVersion, "runtime manifest.version");\n            if (CompareJsonNumberToInteger(rawVersion, 1L) != 0)\n            {\n                throw new ArgumentException("Runtime manifest requires numeric version 1");\n            }\n\n            RequireConstrainedStringMember(root, "body_id", "runtime manifest", 1, 160, BodyIdPattern);\n            RequireConstrainedStringMember(root, "body_name", "runtime manifest", 1, 160, null);\n            RequireConstrainedStringMember(root, "package_sha256", "runtime manifest", 64, 64, Sha256Pattern);\n            RequireConstrainedStringMember(root, "avatar_sha256", "runtime manifest", 64, 64, Sha256Pattern);\n            RequireConstrainedStringMember(root, "bodyprint_sha256", "runtime manifest", 64, 64, Sha256Pattern);\n\n            if (RequireStringMember(root, "avatar", "runtime manifest") != "avatar.vrm")\n            {\n                throw new ArgumentException("Runtime manifest requires avatar.vrm payload path");\n            }\n            if (RequireStringMember(root, "bodyprint", "runtime manifest") != "bodyprint.json")\n            {\n                throw new ArgumentException("Runtime manifest requires bodyprint.json payload path");\n            }\n\n            ValidateRuntimeManifestPayloads(root);\n            return 1;\n        }\n\n        internal static int ValidateMotorStateJson(string json)\n''',
)

replace_once(
    SHIM,
    '        private static int RequireMotorStateVersion(Dictionary<string, string> root)\n',
    '''        private static void ValidateRuntimeManifestPayloads(Dictionary<string, string> root)\n        {\n            if (!root.TryGetValue("payloads", out var rawPayloads))\n            {\n                throw new ArgumentException("Runtime manifest requires payloads array");\n            }\n\n            var payloads = ParseStringArray(rawPayloads, "runtime manifest.payloads");\n            if (payloads.Count < 4 || payloads.Count > 10)\n            {\n                throw new ArgumentOutOfRangeException("runtime manifest.payloads", "Runtime manifest payload count must be in 4..10");\n            }\n\n            var unique = new HashSet<string>(StringComparer.Ordinal);\n            foreach (var payload in payloads)\n            {\n                if (Array.IndexOf(RuntimeManifestPayloads, payload) < 0)\n                {\n                    throw new ArgumentException($"Runtime manifest contains unsupported payload: {payload}");\n                }\n                if (!unique.Add(payload))\n                {\n                    throw new ArgumentException($"Runtime manifest contains duplicate payload: {payload}");\n                }\n            }\n\n            if (!unique.Contains("avatar.vrm") || !unique.Contains("bodyprint.json"))\n            {\n                throw new ArgumentException("Runtime manifest is missing required avatar/bodyprint payloads");\n            }\n        }\n\n        private static List<string> ParseStringArray(string json, string context)\n        {\n            var index = 0;\n            SkipWhitespace(json, ref index);\n            if (index >= json.Length || json[index] != '[')\n            {\n                throw new ArgumentException($"Motor State {context} must be a JSON array");\n            }\n            index++;\n\n            var values = new List<string>();\n            SkipWhitespace(json, ref index);\n            if (index < json.Length && json[index] == ']')\n            {\n                index++;\n                EnsureOnlyTrailingWhitespace(json, index, context);\n                return values;\n            }\n\n            while (index < json.Length)\n            {\n                SkipWhitespace(json, ref index);\n                values.Add(ReadJsonString(json, ref index, context));\n                SkipWhitespace(json, ref index);\n                if (index >= json.Length)\n                {\n                    throw new ArgumentException($"Motor State {context} array is not closed");\n                }\n                if (json[index] == ',')\n                {\n                    index++;\n                    continue;\n                }\n                if (json[index] == ']')\n                {\n                    index++;\n                    EnsureOnlyTrailingWhitespace(json, index, context);\n                    return values;\n                }\n                throw new ArgumentException($"Motor State {context} has invalid JSON array syntax");\n            }\n\n            throw new ArgumentException($"Motor State {context} array is not closed");\n        }\n\n        private static int RequireMotorStateVersion(Dictionary<string, string> root)\n''',
)

replace_once(
    LOADER,
    '            public int version;\n',
    '            public int version { get; set; }\n',
)

replace_once(
    LOADER,
    '''            RuntimeManifest manifest;\n            try\n            {\n                manifest = JsonUtility.FromJson<RuntimeManifest>(File.ReadAllText(fullManifestPath));\n            }\n            catch (Exception exception)\n            {\n                throw new InvalidDataException("BodyRig runtime manifest is not valid JSON", exception);\n            }\n            ValidateRuntimeManifest(manifest);\n''',
    '''            RuntimeManifest manifest;\n            try\n            {\n                var rawManifestJson = File.ReadAllText(fullManifestPath);\n                var validatedVersion = JsonUtility.ValidateRuntimeManifestJson(rawManifestJson);\n                manifest = JsonUtility.FromJson<RuntimeManifest>(rawManifestJson);\n                if (manifest != null)\n                {\n                    manifest.version = validatedVersion;\n                }\n            }\n            catch (Exception exception)\n            {\n                throw new InvalidDataException("BodyRig runtime manifest is not valid JSON", exception);\n            }\n            ValidateRuntimeManifest(manifest);\n''',
)

replace_once(
    LOADER,
    '            if (string.IsNullOrWhiteSpace(manifest.body_id) || string.IsNullOrWhiteSpace(manifest.body_name))\n',
    '            if (string.IsNullOrEmpty(manifest.body_id) || string.IsNullOrEmpty(manifest.body_name))\n',
)

replace_once(
    JSON_GUARD_TEST,
    '    assert used <= {"FromJson", "FromJsonOverwrite", "ToJson", "ValidateMotorStateJson"}\n',
    '    assert used <= {"FromJson", "FromJsonOverwrite", "ToJson", "ValidateMotorStateJson", "ValidateRuntimeManifestJson"}\n',
)

RUNTIME_TEST.write_text(r'''from __future__ import annotations

import json
import re
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SHIM = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigJsonUtility.cs"
LOADER = REPO / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigAvatarLoader.cs"
SCHEMA = REPO / "contracts" / "bodyrig-runtime-assets-v1.schema.json"


def _array_values(source: str, name: str) -> list[str]:
    match = re.search(
        rf"private static readonly string\[\] {re.escape(name)}\s*=\s*\{{(?P<body>.*?)\}};",
        source,
        flags=re.DOTALL,
    )
    assert match is not None, name
    return re.findall(r'"([^"]+)"', match.group("body"))


def test_runtime_manifest_guard_is_schema_derived() -> None:
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    source = SHIM.read_text(encoding="utf-8")
    assert schema["additionalProperties"] is False
    assert set(_array_values(source, "RuntimeManifestFields")) == set(schema["properties"])
    assert set(_array_values(source, "RuntimeManifestPayloads")) == set(
        schema["properties"]["payloads"]["items"]["enum"]
    )
    assert schema["properties"]["format"]["const"] == "bodyrig-runtime-assets"
    assert schema["properties"]["version"]["const"] == 1
    assert schema["properties"]["payloads"]["minItems"] == 4
    assert schema["properties"]["payloads"]["maxItems"] == 10
    assert schema["properties"]["payloads"]["uniqueItems"] is True


def test_runtime_manifest_guard_runs_before_unity_and_owns_version() -> None:
    shim = SHIM.read_text(encoding="utf-8")
    loader = LOADER.read_text(encoding="utf-8")
    entry = shim[
        shim.index("internal static int ValidateRuntimeManifestJson") :
        shim.index("internal static int ValidateMotorStateJson")
    ]
    assert 'ParseObjectMembers(json, "runtime manifest")' in entry
    assert 'RequireExactFields(root, RuntimeManifestFields, "runtime manifest")' in entry
    assert 'CompareJsonNumberToInteger(rawVersion, 1L) != 0' in entry
    assert 'RequireConstrainedStringMember(root, "body_id", "runtime manifest", 1, 160, BodyIdPattern)' in entry
    assert 'RequireConstrainedStringMember(root, "body_name", "runtime manifest", 1, 160, null)' in entry
    assert 'ValidateRuntimeManifestPayloads(root);' in entry

    dto = loader[
        loader.index("private sealed class RuntimeManifest") :
        loader.index("private static readonly HumanBodyBones[] RequiredBones")
    ]
    assert "public int version { get; set; }" in dto
    assert "public int version;" not in dto

    load = loader[
        loader.index("public async Task LoadRuntimeAsync") :
        loader.index("private async Task LoadAvatarPathAsync")
    ]
    raw_guard = "var validatedVersion = JsonUtility.ValidateRuntimeManifestJson(rawManifestJson);"
    unity = "manifest = JsonUtility.FromJson<RuntimeManifest>(rawManifestJson);"
    assign = "manifest.version = validatedVersion;"
    post = "ValidateRuntimeManifest(manifest);"
    assert load.index(raw_guard) < load.index(unity) < load.index(assign) < load.index(post)


def test_runtime_manifest_payload_array_is_bounded_unique_and_canonical() -> None:
    source = SHIM.read_text(encoding="utf-8")
    helper = source[
        source.index("private static void ValidateRuntimeManifestPayloads") :
        source.index("private static int RequireMotorStateVersion")
    ]
    assert 'ParseStringArray(rawPayloads, "runtime manifest.payloads")' in helper
    assert "payloads.Count < 4 || payloads.Count > 10" in helper
    assert "new HashSet<string>(StringComparer.Ordinal)" in helper
    assert "Array.IndexOf(RuntimeManifestPayloads, payload) < 0" in helper
    assert "!unique.Add(payload)" in helper
    assert '!unique.Contains("avatar.vrm") || !unique.Contains("bodyprint.json")' in helper
    assert "ReadJsonString(json, ref index, context)" in helper
    assert "EnsureOnlyTrailingWhitespace(json, index, context)" in helper


def test_generic_jsonutility_paths_remain_motor_optional_only() -> None:
    source = SHIM.read_text(encoding="utf-8")
    wrappers = source[
        source.index("public static T FromJson<T>") :
        source.index("private static void ValidateMotorStatePresenceAndTypes(string json, bool requireMotorState = false)")
    ]
    assert wrappers.count("ValidateMotorStatePresenceAndTypes(json);") == 3
    assert "ValidateRuntimeManifestJson" not in wrappers
''', encoding="utf-8")
