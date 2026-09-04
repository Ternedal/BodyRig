from pathlib import Path


def test_canonical_reference_wrappers_never_skip_fresh_build() -> None:
    for path in (
        Path("run-reference-windows-renderer-probe.ps1"),
        Path("run-reference-quest-renderer-probe.ps1"),
    ):
        script = path.read_text(encoding="utf-8")
        assert "[switch]$SkipBuild" not in script
        assert "SkipBuild = $SkipBuild" not in script
        assert "run-windows-renderer-probe.ps1" in script or "run-quest-renderer-probe.ps1" in script


def test_low_level_renderer_wrappers_keep_skip_build_for_diagnostics_only() -> None:
    windows = Path("run-windows-renderer-probe.ps1").read_text(encoding="utf-8")
    quest = Path("run-quest-renderer-probe.ps1").read_text(encoding="utf-8")

    assert "[switch]$SkipBuild" in windows
    assert "[switch]$SkipBuild" in quest


def test_fresh_reference_builds_clean_the_previous_platform_output_directory() -> None:
    for path in (
        Path("run-windows-renderer-probe.ps1"),
        Path("run-quest-renderer-probe.ps1"),
    ):
        script = path.read_text(encoding="utf-8")
        assert "$buildDir = Split-Path -Parent" in script
        assert "Remove-Item -LiteralPath $buildDir -Recurse -Force" in script


def test_windows_renderer_probe_rejects_nonzero_player_exit_even_if_evidence_exists() -> None:
    windows = Path("run-windows-renderer-probe.ps1").read_text(encoding="utf-8")

    assert "$playerExit = Invoke-NativeProcessWait -FilePath $playerExe -ArgumentList $playerArgs" in windows
    assert "$process.WaitForExit()" in windows
    assert "$playerExit = $LASTEXITCODE" not in windows
    assert "if ($playerExit -ne 0)" in windows
    assert "staged evidence is not authoritative" in windows