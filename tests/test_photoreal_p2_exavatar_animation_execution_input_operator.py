from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p2-exavatar-animation-execution-input.ps1"


def test_execution_input_operator_requires_clean_main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source


def test_execution_input_operator_binds_identity_motion_and_train_ref() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "p2-exavatar-animation-identity.json" in source
    assert "motion-preparation-receipt.json" in source
    assert "motion-preparation" in source
    assert "MotionDriverSourceRef" in source
    assert "--motion-driver-source-ref" in source


def test_execution_input_operator_never_starts_animation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Held-out disclosure:   FALSE" in source
    assert "Animation started:     FALSE" in source
    assert "animation_started" in source
    assert "Start-Process" not in source
    assert "animate.py" not in source


def test_execution_input_operator_checks_narrow_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for field in (
        "identity_artifact_bytes_reverified",
        "motion_driver_artifact_bytes_reverified",
        "train_motion_driver_only",
        "held_out_evaluation_disclosed_to_animation",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_execution_input_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
