from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p2-motion-input-plan.ps1"


def test_p2_motion_input_plan_operator_requires_clean_main_and_exact_inputs() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert 'Join-Path $handoffRoot "p2-motion-evidence-handoff.json"' in source
    assert 'Join-Path $handoffRoot "private-motion-source-index.json"' in source
    assert 'Join-Path $P2Root "p2-motion-source-selection.json"' in source


def test_p2_motion_input_plan_operator_does_no_media_work() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Source media rehash:   NO" in source
    assert "Media preparation:     NOT RUN" in source
    assert "Animation execution:   FALSE" in source
    assert "Get-FileHash" not in source
    assert "ffmpeg" not in source.lower()
    assert "Start-Process" not in source


def test_p2_motion_input_plan_operator_checks_narrow_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for field in (
        "build_private",
        "motion_parameter_extraction_required",
        "motion_input_plan_ready",
        "p2_motion_input_authorized",
        "motion_input_preparation_execution_authorized",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_p2_motion_input_plan_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return

    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
