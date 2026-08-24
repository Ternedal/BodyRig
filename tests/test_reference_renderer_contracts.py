from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
REFERENCE = REPO / "reference-renderer"
UNIVRM_REVISION = "a4711bbf8c4d10659d3e5568c2e3d7d595005e51"


def test_reference_renderer_pins_current_univrm_vrm1_packages() -> None:
    snippet = json.loads(
        (REFERENCE / "Packages" / "bodyrig-univrm-manifest.snippet.json").read_text(encoding="utf-8")
    )
    project = json.loads((REFERENCE / "Packages" / "manifest.json").read_text(encoding="utf-8"))
    expected = {
        "com.unity.mathematics": "1.2.6",
        "com.unity.test-framework": "1.4.6",
        "com.unity.timeline": "1.7.6",
        "com.vrmc.gltf": f"https://github.com/vrm-c/UniVRM.git?path=/Packages/UniGLTF#{UNIVRM_REVISION}",
        "com.vrmc.vrm": f"https://github.com/vrm-c/UniVRM.git?path=/Packages/VRM10#{UNIVRM_REVISION}",
    }
    assert snippet["dependencies"] == expected
    assert project["dependencies"] == expected
    assert "#v0.131.2" not in json.dumps(project)


def test_reference_renderer_is_directly_openable_unity_project() -> None:
    version = (REFERENCE / "ProjectSettings" / "ProjectVersion.txt").read_text(encoding="utf-8")
    assert "m_EditorVersion: 6000.3.13f1" in version
    assert (REFERENCE / "Assets" / "BodyRig" / "Editor" / "BodyRigReferenceBuild.cs").is_file()
    assert (REFERENCE / "Assets" / "BodyRig" / "BodyRigBuildProvenance.cs").is_file()
    assert (REFERENCE / "Assets" / "BodyRig" / "BodyRigPhysicalProbeBootstrap.cs").is_file()
    assert (REFERENCE / "Assets" / "BodyRig" / "BodyRigDeformationSweep.cs").is_file()
    assert (REFERENCE / "build-reference-renderer.ps1").is_file()


def test_machine_probe_rejects_editor_generic_android_and_empty_build_guid() -> None:
    source = (REFERENCE / "Assets" / "BodyRig" / "BodyRigRendererProbe.cs").read_text(encoding="utf-8")
    assert "case RuntimePlatform.WindowsPlayer:" in source
    assert "case RuntimePlatform.WindowsEditor:" in source
    assert "requires a built WindowsPlayer, not Unity Editor" in source
    assert 'deviceModel.IndexOf("Quest", StringComparison.OrdinalIgnoreCase)' in source
    assert 'deviceModel.IndexOf("Oculus", StringComparison.OrdinalIgnoreCase)' in source
    assert "requires a Quest/Oculus device model" in source
    assert "Physical renderer probe requires a non-empty Unity build GUID" in source
    assert '"editor-session"' not in source


def test_probe_remains_manifest_bound_vrm1_only_and_embedded_revision_bound() -> None:
    loader = (REFERENCE / "Assets" / "BodyRig" / "BodyRigAvatarLoader.cs").read_text(encoding="utf-8")
    probe = (REFERENCE / "Assets" / "BodyRig" / "BodyRigRendererProbe.cs").read_text(encoding="utf-8")
    provenance = (REFERENCE / "Assets" / "BodyRig" / "BodyRigBuildProvenance.cs").read_text(encoding="utf-8")
    bootstrap = (REFERENCE / "Assets" / "BodyRig" / "BodyRigPhysicalProbeBootstrap.cs").read_text(encoding="utf-8")
    assert "LoadRuntimeAsync" in loader
    assert "canLoadVrm0X: false" in loader
    assert "await loader.LoadRuntimeAsync(fullManifestPath);" in probe
    assert 'Path.Combine(runtimeDirectory, "avatar.vrm")' in probe
    assert 'Path.Combine(runtimeDirectory, "bodyprint.json")' in probe
    assert "BodyRigBuildProvenance.RequireRevision()" in probe
    assert 'Resources.Load<TextAsset>(ResourceName)' in provenance
    assert 'ResourceName = "bodyrig-build-provenance"' in provenance
    assert "runtime command-line arguments" in provenance
    assert "probe.RunProbeAsync(manifestPath, probePath)" in bootstrap
    assert 'Path.Combine(defaultRoot, "runtime", "runtime-manifest.json")' in bootstrap


def test_physical_bootstrap_runs_fixed_deformation_sweep_before_review_loop() -> None:
    bootstrap = (REFERENCE / "Assets" / "BodyRig" / "BodyRigPhysicalProbeBootstrap.cs").read_text(encoding="utf-8")
    sweep = (REFERENCE / "Assets" / "BodyRig" / "BodyRigDeformationSweep.cs").read_text(encoding="utf-8")
    machine = bootstrap.index("await probe.RunProbeAsync(manifestPath, probePath);")
    deformation = bootstrap.index("await sweep.RunSweepAsync(deformationPath, UpdateSweepStatus);")
    review = bootstrap.index("sweep.BeginReviewLoop(UpdateReviewStatus);")
    assert machine < deformation < review
    assert '"--bodyrig-deformation-output"' in bootstrap
    assert '"humanoid-muscle-sweep-v1"' in sweep
    assert "BodyRigBuildProvenance.RequireRevision()" in sweep
    for pose in (
        '"neutral"', '"arms_abduction"', '"elbows_flexed"',
        '"arms_forward"', '"left_leg_lift"', '"knee_flexion"',
    ):
        assert pose in sweep
    assert "new HumanPoseHandler(_animator.avatar, _animator.transform)" in sweep
    assert "HumanTrait.MuscleName" in sweep
    assert "manual_review_required = true" in sweep
    assert "restored_neutral = true" in sweep


def test_build_script_embeds_exact_clean_git_revision_exact_unity_and_univrm_pins() -> None:
    wrapper = (REFERENCE / "build-reference-renderer.ps1").read_text(encoding="utf-8")
    source = (REFERENCE / "Assets" / "BodyRig" / "Editor" / "BodyRigReferenceBuild.cs").read_text(encoding="utf-8")
    ignore = (REFERENCE / ".gitignore").read_text(encoding="utf-8")
    assert "git -C $repoRoot rev-parse HEAD" in wrapper
    assert "git -C $repoRoot status --porcelain" in wrapper
    assert "checkout is dirty" in wrapper
    assert "renderer-contract.json" in wrapper
    assert "$ExpectedVersion\\Editor\\Unity.exe" in wrapper
    assert "Get-ChildItem -LiteralPath $hubRoot" not in wrapper
    assert "-bodyrigRevision $bodyRigRevision" in wrapper
    assert "-bodyrigUnityVersion $expectedUnityVersion" in wrapper
    assert "BodyRig Git HEAD changed during renderer build" in wrapper
    assert "univrm_revision" in wrapper
    assert "Packages\\manifest.json" in wrapper
    assert "does not pin both UniVRM packages" in wrapper
    assert UNIVRM_REVISION in (REFERENCE / "renderer-contract.json").read_text(encoding="utf-8")
    assert 'GetArgument("-bodyrigRevision")' in source
    assert 'GetArgument("-bodyrigUnityVersion")' in source
    assert "Application.unityVersion" in source
    assert "Physical reference build requires Unity" in source
    assert 'GeneratedProvenancePath = "Assets/BodyRigGenerated/Resources/bodyrig-build-provenance.json"' in source
    assert "bodyrig-build-provenance" in source
    assert "AssetDatabase.ImportAsset(GeneratedProvenancePath" in source
    assert "Assets/BodyRigGenerated/" in ignore


def test_build_script_has_physical_windows_and_quest_targets() -> None:
    source = (REFERENCE / "Assets" / "BodyRig" / "Editor" / "BodyRigReferenceBuild.cs").read_text(encoding="utf-8")
    assert "BuildTarget.StandaloneWindows64" in source
    assert "BuildTarget.Android" in source
    assert "AndroidArchitecture.ARM64" in source
    assert 'ApplicationId = "dk.ternedal.bodyrig.reference"' in source
    assert "BuildOptions.Development" in source


def test_operator_wrappers_keep_gate_a_bytes_platform_deformation_and_build_revision_identity() -> None:
    windows = (REPO / "run-windows-renderer-probe.ps1").read_text(encoding="utf-8")
    quest = (REPO / "run-quest-renderer-probe.ps1").read_text(encoding="utf-8")
    for source in (windows, quest):
        assert "bodyrig-acceptance.json" in source
        assert "runtime-manifest.json" in source
        assert "manifest_sha256" in source
        assert "Get-FileHash" in source
        assert "production_activation" in source
        assert "bodyrig-deformation-probe" in source
        assert "humanoid-muscle-sweep-v1" in source
        assert "neutral,arms_abduction,elbows_flexed,arms_forward,left_leg_lift,knee_flexion" in source
        assert "deformation.package_sha256" in source
        assert "deformation.avatar_sha256" in source
        assert "deformation.bodyprint_sha256" in source
        assert "acceptance.bodyrig_revision" in source
        assert "probe.bodyrig_revision" in source
        assert "deformation.bodyrig_revision" in source
        assert "checkout is dirty" in source
    assert 'unity_platform -ne "WindowsPlayer"' in windows
    assert 'platform -ne "windows-unity-univrm"' in windows
    assert 'platform -ne "android-quest-class"' in quest
    assert "getprop" in quest and "ro.product.model" in quest
    assert "quest|oculus" in quest.lower()
    assert 'ApplicationId = "dk.ternedal.bodyrig.reference"' in quest


def test_physical_wrappers_commit_machine_and_deformation_as_one_directory_pair() -> None:
    windows = (REPO / "run-windows-renderer-probe.ps1").read_text(encoding="utf-8")
    quest = (REPO / "run-quest-renderer-probe.ps1").read_text(encoding="utf-8")
    expected = (
        (windows, "windows-evidence", ".bodyrig-windows-attempt-"),
        (quest, "quest-evidence", ".bodyrig-quest-attempt-"),
    )
    for source, evidence_dir, attempt_prefix in expected:
        assert evidence_dir in source
        assert attempt_prefix in source
        assert '$committed = $false' in source
        assert 'Move-Item -LiteralPath $attemptDir -Destination $evidenceDir' in source
        assert '$committed = $true' in source
        assert 'if (-not $committed -and (Test-Path -LiteralPath $attemptDir -PathType Container))' in source
        assert 'Remove-Item -LiteralPath $attemptDir -Recurse -Force' in source
        assert 'canonical evidence directory already exists' in source
        assert 'Pass both -ProbeOutput and -DeformationOutput together, or neither.' in source
        assert 'must share one dedicated evidence directory' in source
