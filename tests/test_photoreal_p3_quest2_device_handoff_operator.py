from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p3-quest2-device-handoff.ps1"


def test_p3_quest2_device_handoff_requires_exact_physical_target() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'target_device_family -ne "meta-quest"' in source
    assert 'target_device_model -ne "quest-2"' in source
    assert "Connected device does not identify itself explicitly as Quest 2" in source


def test_p3_quest2_device_handoff_uses_pinned_unity_adb() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "reference-renderer\\renderer-contract.json" in source
    assert "PlaybackEngines\\AndroidPlayer\\SDK\\platform-tools" in source
    assert "refuses non-pinned adb" in source


def test_p3_quest2_device_handoff_rehashes_local_and_roundtrip_bytes() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Quest2 student artifact bytes drifted" in source
    assert '@("push", [string]$artifact.local_path, $remotePath)' in source
    assert '@("pull", $remotePath, $roundtripPath)' in source
    assert "roundtrip_sha256 = $roundtripSha" in source
    assert "staged_student_hashes_roundtrip_verified = $true" in source


def test_p3_quest2_device_handoff_never_claims_runtime_installation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "runtime_loaded = $false" in source
    assert "installed_student_hashes_verified_on_device = $false" in source
    assert "human_runtime_visual_acceptance_complete = $false" in source
    assert "runtime_acceptance_authority = $false" in source
    assert "photoreal_acceptance_authority = $false" in source
    assert "production_activation = $false" in source
    assert "staged bytes are NOT runtime installation evidence" in source


def test_p3_quest2_device_handoff_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
