from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
REFERENCE = REPO / "reference-renderer"


def test_reference_renderer_pins_current_univrm_vrm1_packages() -> None:
    snippet = json.loads(
        (REFERENCE / "Packages" / "bodyrig-univrm-manifest.snippet.json").read_text(encoding="utf-8")
    )
    project = json.loads((REFERENCE / "Packages" / "manifest.json").read_text(encoding="utf-8"))
    expected = {
        "com.vrmc.gltf": "https://github.com/vrm-c/UniVRM.git?path=/Packages/UniGLTF#v0.131.2",
        "com.vrmc.vrm": "https://github.com/vrm-c/UniVRM.git?path=/Packages/VRM10#v0.131.2",
    }
    assert snippet["dependencies"] == expected
    assert project["dependencies"] == expected


def test_reference_renderer_is_directly_openable_unity_project() -> None:
    version = (REFERENCE / "ProjectSettings" / "ProjectVersion.txt").read_text(encoding="utf-8")
    assert "m_EditorVersion: 6000.3.13f1" in version
    assert (REFERENCE / "Assets" / "BodyRig" / "Editor" / "BodyRigReferenceBuild.cs").is_file()
    assert (REFERENCE / "Assets" / "BodyRig" / "BodyRigPhysicalProbeBootstrap.cs").is_file()
    assert (REFERENCE / "build-reference-renderer.ps1").is_file()


def test_machine_probe_rejects_editor_generic_android_and_empty_build_guid() -> None:
    source = (REFERENCE / "Assets" / "BodyRig" / "BodyRigRendererProbe.cs").read_text(
        encoding="utf-8"
    )
    assert "case RuntimePlatform.WindowsPlayer:" in source
    assert "case RuntimePlatform.WindowsEditor:" in source
    assert "requires a built WindowsPlayer, not Unity Editor" in source
    assert 'deviceModel.IndexOf("Quest", StringComparison.OrdinalIgnoreCase)' in source
    assert 'deviceModel.IndexOf("Oculus", StringComparison.OrdinalIgnoreCase)' in source
    assert "requires a Quest/Oculus device model" in source
    assert "Physical renderer probe requires a non-empty Unity build GUID" in source
    assert '"editor-session"' not in source


def test_probe_remains_manifest_bound_and_vrm1_only() -> None:
    loader = (REFERENCE / "Assets" / "BodyRig" / "BodyRigAvatarLoader.cs").read_text(
        encoding="utf-8"
    )
    probe = (REFERENCE / "Assets" / "BodyRig" / "BodyRigRendererProbe.cs").read_text(
        encoding="utf-8"
    )
    bootstrap = (REFERENCE / "Assets" / "BodyRig" / "BodyRigPhysicalProbeBootstrap.cs").read_text(
        encoding="utf-8"
    )
    assert "LoadRuntimeAsync" in loader
    assert "canLoadVrm0X: false" in loader
    assert "await loader.LoadRuntimeAsync(fullManifestPath);" in probe
    assert 'Path.Combine(runtimeDirectory, "avatar.vrm")' in probe
    assert 'Path.Combine(runtimeDirectory, "bodyprint.json")' in probe
    assert "probe.RunProbeAsync(manifestPath, probePath)" in bootstrap
    assert 'Path.Combine(defaultRoot, "runtime", "runtime-manifest.json")' in bootstrap


def test_build_script_has_physical_windows_and_quest_targets() -> None:
    source = (REFERENCE / "Assets" / "BodyRig" / "Editor" / "BodyRigReferenceBuild.cs").read_text(
        encoding="utf-8"
    )
    assert "BuildTarget.StandaloneWindows64" in source
    assert "BuildTarget.Android" in source
    assert "AndroidArchitecture.ARM64" in source
    assert 'ApplicationId = "dk.ternedal.bodyrig.reference"' in source
    assert "BuildOptions.Development" in source
