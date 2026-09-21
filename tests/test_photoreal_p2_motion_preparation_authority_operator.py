from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "authorize-photoreal-v2-p2-motion-preparation.ps1"


def test_p2_motion_preparation_authority_operator_binds_p0_scan_plan() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '[Parameter(Mandatory = $true)][string]$P0Root' in source
    assert 'Join-Path $P0Root "scan-plan.json"' in source
    assert '"--scan-plan", $scanPlan' in source
    assert '"--input-plan", $inputPlan' in source
    assert 'p2-motion-preparation-authority.json' in source


def test_p2_motion_preparation_authority_operator_is_non_executing() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Source media rehash:  NO" in source
    assert "Media preparation:    NOT RUN" in source
    assert "Animation execution:  FALSE" in source
    assert "Get-FileHash" not in source
    assert "ffmpeg" not in source.lower()
    assert "Start-Process" not in source


def test_p2_motion_preparation_authority_operator_checks_narrow_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "scan_plan_projection_authority_reused" in source
    assert "motion_input_preparation_execution_authorized" in source
    for field in (
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_p2_motion_preparation_authority_operator_requires_clean_main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source


def test_p2_motion_preparation_authority_operator_powershell_parses_when_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return

    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
