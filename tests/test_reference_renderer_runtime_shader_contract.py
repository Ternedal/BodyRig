from pathlib import Path


BUILD = Path("reference-renderer/Assets/BodyRig/Editor/BodyRigReferenceBuild.cs")


def test_reference_renderer_retains_univrm_runtime_shaders() -> None:
    source = BUILD.read_text(encoding="utf-8")

    assert '"Standard"' in source
    assert '"UniGLTF/UniUnlit"' in source
    assert '"VRM10/MToon10"' in source
    assert "EnsureRuntimeShaderAnchors();" in source
    assert 'GeneratedResourcesPath = "Assets/BodyRigGenerated/Resources"' in source
    assert "Shader.Find(entry.ShaderName)" in source
    assert "AssetDatabase.CreateAsset(material, assetPath)" in source
    assert "AssetDatabase.SaveAssets();" in source
    assert "player stripping" in source


def test_shader_anchors_are_generated_only_not_source_runtime_payloads() -> None:
    source = BUILD.read_text(encoding="utf-8")

    assert 'bodyrig-shader-anchor-standard.mat' in source
    assert 'bodyrig-shader-anchor-uniunlit.mat' in source
    assert 'bodyrig-shader-anchor-mtoon10.mat' in source
    assert "Assets/BodyRigGenerated/Resources" in source
    assert "runtime-manifest.json" not in source
    assert "avatar.vrm" not in source
