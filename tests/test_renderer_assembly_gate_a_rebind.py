from pathlib import Path


SCRIPT = Path("rebind-gate-a-renderer-assembly-revision.ps1")


def test_renderer_assembly_rebind_is_exact_and_non_recomputing() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for path in (
        "reference-renderer/Assets/BodyRig/BodyRig.ReferenceRenderer.Runtime.asmdef",
        "reference-renderer/Assets/BodyRig/Editor/BodyRig.ReferenceRenderer.Editor.asmdef",
        "tests/test_reference_renderer_assembly_boundaries.py",
        "rebind-gate-a-renderer-assembly-revision.ps1",
        "tests/test_renderer_assembly_gate_a_rebind.py",
    ):
        assert f'"{path}"' in source

    assert "diff --name-status" in source
    assert "merge-base --is-ancestor" in source
    assert "Revision delta is broader than the approved renderer-assembly repair/rebind set" in source
    assert 'Copy-Item -LiteralPath $SourceAcceptanceDir -Destination $attempt -Recurse' in source
    assert 'package_bytes_preserved = $true' in source
    assert 'runtime_bytes_preserved = $true' in source
    assert 'recovery_rerun = $false' in source
    assert 'clone_rerun = $false' in source
    assert 'renderer_assembly_revision_rebind_sha256' in source
    assert 'BodyRig renderer assembly revision rebind: PASS' in source


def test_renderer_assembly_rebind_keeps_runtime_and_package_bytes_immutable() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'Renderer assembly rebind changed package bytes.' in source
    assert 'Renderer assembly rebind changed runtime-manifest bytes.' in source
    assert 'Renderer assembly rebind changed runtime payload bytes: $payloadName' in source
    assert 'foreach ($payloadName in @("avatar.vrm", "bodyprint.json"))' in source
    assert '$acceptance.bodyrig_revision = $head' in source
    assert '$acceptance.package.package_sha256 =' not in source
    assert '$acceptance.runtime.manifest_sha256 =' not in source
