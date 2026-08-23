from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
REFERENCE = REPO / "reference-renderer"


def test_reference_renderer_pins_current_univrm_vrm1_packages() -> None:
    manifest = json.loads(
        (REFERENCE / "Packages" / "bodyrig-univrm-manifest.snippet.json").read_text(encoding="utf-8")
    )
    dependencies = manifest["dependencies"]
    assert set(dependencies) == {"com.vrmc.gltf", "com.vrmc.vrm"}
    assert dependencies["com.vrmc.gltf"].endswith("/Packages/UniGLTF#v0.131.2")
    assert dependencies["com.vrmc.vrm"].endswith("/Packages/VRM10#v0.131.2")


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
    assert "LoadRuntimeAsync" in loader
    assert "canLoadVrm0X: false" in loader
    assert "await loader.LoadRuntimeAsync(fullManifestPath);" in probe
    assert 'Path.Combine(runtimeDirectory, "avatar.vrm")' in probe
    assert 'Path.Combine(runtimeDirectory, "bodyprint.json")' in probe
