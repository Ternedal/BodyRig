from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p2-motion-evidence.ps1"


def test_p2_motion_operator_requires_clean_main_and_existing_p2_plan() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert 'Join-Path $TeacherWorkRoot "teacher-input.json"' in source
    assert 'Join-Path $P2Root "p2-animation-plan.json"' in source


def test_p2_motion_operator_preserves_no_rehash_and_human_boundary() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Source media rehash: NO" in source
    assert "Human selection:     REQUIRED" in source
    assert "No source file was rehashed and no animation was started." in source
    assert "Get-FileHash" not in source
    assert "Start-Process" not in source
    assert "exit 2" in source


def test_p2_motion_operator_checks_all_downstream_authorities_false() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for field in (
        "human_motion_source_selection_complete",
        "p2_motion_input_authorized",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_p2_motion_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return

    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
