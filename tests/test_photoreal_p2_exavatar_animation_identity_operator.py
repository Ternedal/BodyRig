from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p2-exavatar-animation-identity.ps1"


def test_operator_uses_exact_teacher_config_workspace_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'exavatar-teacher-config.json' in source
    assert 'Get-ConfigArg -Command $command -Name "--workspace-root"' in source
    assert 'Get-ConfigArg -Command $command -Name "--distribution"' in source
    assert 'Get-ConfigArg -Command $command -Name "--linux-python"' in source
    assert 'Get-ConfigArg -Command $command -Name "--wsl-exe"' in source
    assert "d45268730c779fae4118f1a361cf9ff639bc4d1e" in source
    assert '$config.version -is [bool]' in source


def test_operator_uses_wsl_module_and_accepted_teacher_output() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "bodyrig.photoreal_p2_exavatar_animation_identity" in source
    assert '"--animation-plan", $linuxPlan' in source
    assert '"--exavatar-workspace-root", $linuxWorkspace' in source
    assert '"--teacher-output-root", $linuxTeacherOutput' in source
    assert 'exavatar-teacher-output\\output' in source


def test_operator_does_not_rehash_source_media_or_start_execution() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Source media rehash:  NO" in source
    assert "Fitting/training:     NOT RUN" in source
    assert "Animation execution:  FALSE" in source
    assert "Get-FileHash" not in source
    assert "animate.py" not in source
    assert "Start-Process" not in source


def test_operator_checks_non_escalating_receipt_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "teacher_checkpoint_bytes_reverified" in source
    assert "identity_bytes_reverified_against_preprocess_state" in source
    assert "p2_animation_identity_input_ready" in source
    for field in (
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_operator_requires_clean_main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source


def test_operator_powershell_parses_when_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
