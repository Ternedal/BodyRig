from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "reference-renderer" / "Assets" / "BodyRig" / "BodyRigRendererProbe.cs"


def source() -> str:
    return PROBE.read_text(encoding="utf-8")


def test_physical_probe_requires_promoted_component_renderers_when_vrm_carries_them() -> None:
    text = source()

    for node in (
        "BodyRigSourceHairReview",
        "BodyRigSourceEyeReview",
        "BodyRigFaceSecondaryReview",
        "BodyRigFingernailPlates",
        "BodyRigToenailPlates",
    ):
        assert node in text

    assert "RequireExpectedComponentRenderers(avatarPath, loader.Active.gameObject, animator);" in text
    assert "File.ReadAllBytes(avatarPath)" in text
    assert "ContainsAscii(bytes, expected.NodeName)" in text
    assert "activeRoot.GetComponentsInChildren<Transform>(true)" in text
    assert "matched.GetComponentsInChildren<SkinnedMeshRenderer>(true)" in text
    assert "renderer.sharedMesh.vertexCount <= 0" in text
    assert "renderer.forceRenderingOff" in text
    assert "renderer.gameObject.activeInHierarchy" in text
    assert "UniVRM did not instantiate that node" in text


def test_hair_and_eyes_require_finite_non_degenerate_head_local_drawable_rendering() -> None:
    text = source()

    assert 'new ExpectedRenderPayload("hair", "BodyRigSourceHairReview", true, 0.60f)' in text
    assert 'new ExpectedRenderPayload("eyes", "BodyRigSourceEyeReview", true, 0.30f)' in text
    assert "animator.GetBoneTransform(HumanBodyBones.Head)" in text
    assert "bounds.extents.sqrMagnitude < MinimumDrawableBoundsSqrMagnitude" in text
    assert "bounds.SqrDistance(head.position)" in text
    assert "expected.MaximumHeadDistanceMeters * expected.MaximumHeadDistanceMeters" in text
    assert "!IsFinite(bounds.center) || !IsFinite(bounds.size)" in text
    assert "HasDrawableMaterial(renderer)" in text
    assert "material.shader == null || material.passCount <= 0" in text
    assert 'material.HasProperty("_BaseColor")' in text
    assert 'material.HasProperty("_Color")' in text
    assert "alpha <= MinimumMaterialAlpha" in text
    assert "no active physically drawable skinned renderer" in text


def test_component_instantiation_guard_runs_after_exact_runtime_hash_recheck() -> None:
    text = source()

    avatar_hash = text.index("var avatarHash = Sha256File(avatarPath);")
    avatar_binding = text.index("loader.ActiveAvatarSha256")
    component_guard = text.index(
        "RequireExpectedComponentRenderers(avatarPath, loader.Active.gameObject, animator);"
    )
    report = text.index("var report = new ProbeReport")

    assert avatar_hash < avatar_binding < component_guard < report


def test_hair_deformation_probe_remains_separate_machine_evidence() -> None:
    deformation = (
        ROOT
        / "reference-renderer"
        / "Assets"
        / "BodyRig"
        / "BodyRigHairDeformationProbe.cs"
    ).read_text(encoding="utf-8")

    assert "Hair deformation probe" in deformation
    assert "hair_component_authority = false" in deformation
    assert "human_review_required = true" in deformation
    assert "production_activation = false" in deformation
