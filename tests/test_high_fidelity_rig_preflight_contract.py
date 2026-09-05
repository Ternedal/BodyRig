from pathlib import Path


def test_rig_preflight_checks_pinned_renderer_toolchain_without_writing_evidence() -> None:
    root = Path(__file__).resolve().parents[1]
    source = (root / "high-fidelity-rig-preflight.ps1").read_text(encoding="utf-8")

    assert "renderer-contract.json" in source
    assert "unity_editor_version" in source
    assert "Android Build Support" in source
    assert "SDK\\platform-tools\\adb.exe" in source
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
