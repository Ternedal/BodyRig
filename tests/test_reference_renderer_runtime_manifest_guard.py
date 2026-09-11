from __future__ import annotations

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
