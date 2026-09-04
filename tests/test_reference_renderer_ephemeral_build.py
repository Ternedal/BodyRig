from pathlib import Path


BUILD = Path("reference-renderer/build-reference-renderer.ps1")


def test_renderer_build_uses_ephemeral_unity_project_and_never_source_project() -> None:
    script = BUILD.read_text(encoding="utf-8")

    assert '"BodyRig-reference-build-"' in script
    assert '$tempProject = Join-Path $tempRoot "reference-renderer"' in script
    assert "Copy-ReferenceProject -Source $projectRoot -Destination $tempProject" in script
    assert '"-projectPath", $tempProject' in script
    assert '"-projectPath", $projectRoot' not in script
    assert "Remove-Item -LiteralPath $tempRoot -Recurse -Force" in script


def test_renderer_build_validates_unity_resolved_package_lock() -> None:
    script = BUILD.read_text(encoding="utf-8")

    assert 'Packages\\packages-lock.json' in script
    assert "Assert-ResolvedPackageLock" in script
    assert '"com.vrmc.gltf", "com.vrmc.vrm"' in script
    assert 'if ([string]$entry.source -ne "git")' in script
    assert "entry.hash -ne $ExpectedUniVrmRevision" in script
    assert '"com.unity.test-framework" = "1.6.0"' in script
    assert '"com.unity.mathematics" = "1.2.6"' in script
    assert '"com.unity.timeline" = "1.7.6"' in script
    assert "Unity package resolution was not validated." in script


def test_renderer_build_rechecks_source_checkout_after_ephemeral_build() -> None:
    script = BUILD.read_text(encoding="utf-8")

    assert script.count("git -C $repoRoot status --porcelain") >= 2
    assert "Renderer build changed tracked/unignored BodyRig checkout state" in script
    assert "BodyRig Git HEAD changed during renderer build" in script
