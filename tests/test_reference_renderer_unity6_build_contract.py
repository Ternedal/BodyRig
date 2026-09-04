from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "reference-renderer"


def test_batch_build_starts_unity_on_the_requested_physical_target() -> None:
    wrapper = (REFERENCE / "build-reference-renderer.ps1").read_text(encoding="utf-8")

    assert '$unityBuildTarget = if ($Platform -eq "Windows") { "StandaloneWindows64" } else { "Android" }' in wrapper
    assert '"-buildTarget", $unityBuildTarget' in wrapper
    assert '"-projectPath", $tempProject' in wrapper
    assert '"-executeMethod", $method' in wrapper
    assert wrapper.index('"-buildTarget", $unityBuildTarget') < wrapper.index('"-projectPath", $tempProject') < wrapper.index('"-executeMethod", $method')


def test_quest_build_pins_il2cpp_before_arm64() -> None:
    source = (REFERENCE / "Assets" / "BodyRig" / "Editor" / "BodyRigReferenceBuild.cs").read_text(encoding="utf-8")

    assert "using UnityEditor.Build;" in source
    assert "PlayerSettings.SetScriptingBackend(NamedBuildTarget.Android, ScriptingImplementation.IL2CPP);" in source
    assert "PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;" in source
    assert source.index("SetScriptingBackend(NamedBuildTarget.Android") < source.index("targetArchitectures = AndroidArchitecture.ARM64")
