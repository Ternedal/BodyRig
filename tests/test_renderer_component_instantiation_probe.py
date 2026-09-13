from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigRendererProbe.cs"


def test_physical_probe_requires_promoted_component_renderers_when_vrm_carries_them() -> None:
    source = PROBE.read_text(encoding="utf-8")

    for node in (
        "BodyRigSourceHairReview",
        "BodyRigSourceEyeReview",
        "BodyRigFaceSecondaryReview",
    ):
        assert node in source

    assert "RequireExpectedComponentRenderers(avatarPath, loader.Active.gameObject);" in source
    assert "File.ReadAllBytes(avatarPath)" in source
    assert "ContainsAscii(bytes, expected.NodeName)" in source
    assert "activeRoot.GetComponentsInChildren<Transform>(true)" in source
    assert "matched.GetComponentsInChildren<SkinnedMeshRenderer>(true)" in source
    assert "renderer.sharedMesh.vertexCount <= 0" in source
    assert "renderer.sharedMaterials.Length == 0" in source
    assert "renderer.forceRenderingOff" in source
    assert "renderer.gameObject.activeInHierarchy" in source
    assert "UniVRM did not instantiate that node" in source
    assert "no active skinned renderer with mesh/materials is visible" in source


def test_component_instantiation_guard_runs_after_exact_runtime_hash_recheck() -> None:
    source = PROBE.read_text(encoding="utf-8")

    avatar_hash = source.index("var avatarHash = Sha256File(avatarPath);")
    avatar_binding = source.index("loader.ActiveAvatarSha256")
    component_guard = source.index(
        "RequireExpectedComponentRenderers(avatarPath, loader.Active.gameObject);"
    )
    report = source.index("var report = new ProbeReport")

    assert avatar_hash < avatar_binding < component_guard < report
