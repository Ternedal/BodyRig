from pathlib import Path


def test_rig_preflight_checks_pinned_renderer_toolchain_without_writing_evidence() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "high-fidelity-rig-preflight.ps1").read_text(encoding="utf-8")

    assert "check-reference-renderer-ready.ps1" in source
    assert "$rendererReadinessScript" in source
    assert "& $rendererReadinessScript" in source
    assert "renderer-contract.json" in source
    assert "unity_editor_version" in source
    assert "Android Build Support" in source
    assert "SDK\\platform-tools\\adb.exe" in source
    assert 'Need-File $adbCandidate "Pinned Unity Android adb"' in source
    assert "Get-Command adb" not in source
    assert "adb devices" in source
    assert "bodyrig.__file__" in source
    assert "git -C $repoRoot status --porcelain" in source
    assert "No acceptance evidence was created or modified" in source
    assert "prepare-high-fidelity-physical-acceptance.ps1" in source
    assert "run-windows-renderer-probe.ps1" in source
    assert "run-quest-renderer-probe.ps1" in source
    assert "complete-acceptance.ps1" in source
    assert "Set-Content" not in source
    assert "Out-File" not in source


def test_rig_preflight_delegates_renderer_manifest_and_project_pin_validation_to_canonical_checker() -> None:
    root = Path(__file__).resolve().parents[1]
    preflight = (root / "high-fidelity-rig-preflight.ps1").read_text(encoding="utf-8")
    canonical = (root / "check-reference-renderer-ready.ps1").read_text(encoding="utf-8")

    assert 'Need-File (Join-Path $repoRoot "check-reference-renderer-ready.ps1")' in preflight
    assert "ProjectSettings\\ProjectVersion.txt" in canonical
    assert "Reference renderer project version does not match renderer-contract Unity version" in canonical
    assert "Reference renderer package manifest dependency set is not canonical" in canonical
    assert "com.vrmc.gltf" in canonical
    assert "com.vrmc.vrm" in canonical
