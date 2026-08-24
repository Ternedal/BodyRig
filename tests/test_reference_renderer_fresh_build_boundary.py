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
