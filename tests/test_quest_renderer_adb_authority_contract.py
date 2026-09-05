from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "run-quest-renderer-probe.ps1"
REFERENCE = ROOT / "run-reference-quest-renderer-probe.ps1"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_quest_probe_layers_never_default_to_path_adb() -> None:
    for path in (CORE, REFERENCE):
        text = _text(path)
        assert '[string]$AdbExe = "adb"' not in text
        assert '[string]$AdbExe = ""' in text
        assert "reference-renderer\\renderer-contract.json" in text
        assert "PlaybackEngines\\AndroidPlayer\\SDK\\platform-tools" in text
        assert '"adb.exe"' in text
        assert "pinned Unity Android SDK adb.exe" in text
        assert "OrdinalIgnoreCase" in text


def test_core_quest_probe_uses_only_resolved_pinned_adb() -> None:
    text = _text(CORE)
    authority = text.index("$pinnedAdb = Join-Path")
    assignment = text.index("$script:AdbExe = $pinnedAdb")
    first_adb_use = text.index('Invoke-Adb -Arguments @("devices")')

    assert authority < assignment < first_adb_use
    assert "Get-Command $AdbExe" not in text
    assert "refusing alternate adb" in text


def test_reference_wrapper_validates_adb_before_inner_probe() -> None:
    text = _text(REFERENCE)
    authority = text.index("$pinnedAdb = Join-Path")
    rejection = text.index("refusing alternate adb")
    inner_call = text.index("& $inner @args")

    assert authority < rejection < inner_call
    assert "AdbExe = $AdbExe" in text
    assert "Get-Command $AdbExe" not in text


def test_core_quest_probe_hands_off_only_to_reference_attestation() -> None:
    text = _text(CORE)
    assert "record-reference-renderer-acceptance.ps1" in text
    assert "with record-renderer-acceptance.ps1" not in text
