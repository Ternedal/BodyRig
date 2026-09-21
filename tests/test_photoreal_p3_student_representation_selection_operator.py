from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p3-student-representation.ps1"


def test_operator_requires_clean_main_and_existing_p3_plan() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert "p3-device-distillation-plan.json" in source


def test_operator_keeps_adapter_and_distillation_fail_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Student representation: SELECTED" in source
    assert "Distillation adapter:    NOT SELECTED" in source
    assert "Distillation run:        NOT STARTED" in source
    assert "distillation_job_start_authorized" in source
    assert "runtime_acceptance_authority" in source
    assert "production_activation" in source


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
