from pathlib import Path


SCRIPT = Path("rebind-gate-a-renderer-build-revision.ps1")


def test_renderer_build_rebind_is_exact_and_non_recomputing() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for path in (
        "reference-renderer/Assets/BodyRig/Editor/BodyRigReferenceBuild.cs",
        "tests/test_reference_renderer_contracts.py",
        "rebind-gate-a-renderer-build-revision.ps1",
        "tests/test_renderer_build_gate_a_rebind.py",
    ):
        assert f'"{path}"' in source

    assert "diff --name-status" in source
    assert "merge-base --is-ancestor" in source
    assert "Revision delta is broader than the approved renderer-build repair/rebind set" in source
    assert 'package_bytes_preserved = $true' in source
    assert 'runtime_bytes_preserved = $true' in source
    assert 'recovery_rerun = $false' in source
    assert 'clone_rerun = $false' in source
    assert 'renderer_build_revision_rebind_sha256' in source
    assert 'repair_scope = "reference-renderer-build-only"' in source
    assert 'BodyRig renderer build revision rebind: PASS' in source


def test_renderer_build_rebind_requires_prior_build_bound_source_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "physical_clone.reconciled" not in source
    assert '[string]$physicalClone.mode -ne "stash-sith-high-fidelity"' in source
    assert "$physicalClone.session_sha256" in source
    assert "$physicalClone.readiness_sha256" in source
    assert "$physicalClone.renderer_build_revision_rebind_sha256" in source
    assert "bodyrig-renderer-build-revision-rebind.json" in source
    assert "Source Gate A renderer build revision rebind bytes no longer match acceptance authority." in source


def test_renderer_build_rebind_keeps_gate_a_payload_bytes_immutable() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'Renderer build rebind changed package bytes.' in source
    assert 'Renderer build rebind changed runtime-manifest bytes.' in source
    assert 'Renderer build rebind changed runtime payload bytes: $payloadName' in source
    assert 'foreach ($payloadName in @("avatar.vrm", "bodyprint.json"))' in source
    assert '$acceptance.bodyrig_revision = $head' in source
    assert '$acceptance.package.package_sha256 =' not in source
    assert '$acceptance.runtime.manifest_sha256 =' not in source
