from pathlib import Path


SCRIPT = Path("rebind-gate-a-renderer-bundle-revision.ps1")


def test_renderer_bundle_rebind_is_exact_non_recomputing_and_pre_physical() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for path in (
        "rebind-gate-a-renderer-assembly-revision.ps1",
        "rebind-gate-a-renderer-package-revision.ps1",
        "rebind-gate-a-renderer-revision.ps1",
        "rebind-gate-a-renderer-shader-revision.ps1",
        "rebind-gate-a-renderer-bundle-revision.ps1",
        "reference-renderer/Assets/BodyRig/BodyRig.ReferenceRenderer.Runtime.asmdef",
        "reference-renderer/Assets/BodyRig/BodyRigAvatarLoader.cs",
        "reference-renderer/Assets/BodyRig/Editor/BodyRig.ReferenceRenderer.Editor.asmdef",
        "reference-renderer/Assets/BodyRig/Editor/BodyRigReferenceBuild.cs",
        "reference-renderer/Packages/bodyrig-univrm-manifest.snippet.json",
        "reference-renderer/Packages/manifest.json",
        "reference-renderer/build-reference-renderer.ps1",
        "tests/test_reference_renderer_assembly_boundaries.py",
        "tests/test_reference_renderer_build_contract.py",
        "tests/test_reference_renderer_contracts.py",
        "tests/test_reference_renderer_ephemeral_build.py",
        "tests/test_reference_renderer_package_resolution_contract.py",
        "tests/test_reference_renderer_runtime_shader_contract.py",
        "tests/test_reference_renderer_unity6_build_contract.py",
        "tests/test_renderer_assembly_gate_a_rebind.py",
        "tests/test_renderer_gate_a_rebind.py",
        "tests/test_renderer_package_gate_a_rebind.py",
        "tests/test_renderer_shader_gate_a_rebind.py",
        "tests/test_renderer_bundle_gate_a_rebind.py",
    ):
        assert f'"{path}"' in source

    assert "diff --name-status" in source
    assert "merge-base --is-ancestor" in source
    assert "Source Gate A is not rooted in the reconciled physical clone" in source
    assert "Renderer bundle rebind must happen before physical renderer evidence exists" in source
    assert '"bodyrig-physical-clone-reconciliation.json"' in source
    assert "Renderer bundle rebind changed package bytes." in source
    assert "Renderer bundle rebind changed runtime-manifest bytes." in source
    assert 'foreach ($payloadName in @("avatar.vrm", "bodyprint.json"))' in source
    assert "physical_evidence_bytes_preserved = $true" in source
    assert "recovery_rerun = $false" in source
    assert "clone_rerun = $false" in source
    assert "$acceptance.bodyrig_revision = $head" in source
    assert "$acceptance.package.package_sha256 =" not in source
    assert "$acceptance.runtime.manifest_sha256 =" not in source
    assert "Recovery rerun:         NO" in source
    assert "Clone rerun:            NO" in source
