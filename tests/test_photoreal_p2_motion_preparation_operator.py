from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-photoreal-v2-p2-motion-preparation.ps1"


def test_operator_requires_clean_main_and_original_p0_scan_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert 'Join-Path $P0Root "scan-plan.json"' in source
    assert 'Join-Path $P2Root "motion-input"' in source
    assert 'Join-Path $motionInputRoot "p2-motion-input-plan.json"' in source
    assert 'Join-Path $motionInputRoot "p2-motion-normalization-selection.json"' in source
    assert 'Join-Path $motionInputRoot "p2-motion-window-selection.json"' in source
    assert '"--normalization-selection", $normalizationSelection' in source
    assert '"--window-selection", $windowSelection' in source


def test_operator_marks_first_physical_motion_stage_without_source_library_rehash() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "first P2 stage that may decode/deproject selected videos and run motion fitting" in source
    assert "It does not rehash the full source media library." in source
    assert "Get-FileHash" not in source


def test_operator_requires_core_verified_motion_paths_before_animation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for field in (
        "generated_artifact_bytes_verified_by_core",
        "motion_input_preparation_complete",
        "p2_animation_execution_authorized",
        "source_media_rehash_performed",
        "evaluation_appearance_training_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
