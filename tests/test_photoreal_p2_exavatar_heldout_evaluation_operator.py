from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p2-exavatar-heldout-evaluation-input.ps1"


def test_heldout_operator_requires_clean_main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source


def test_heldout_operator_requires_completed_train_execution() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "animation-execution-receipt.json" in source
    assert "HeldOutSourceRef" in source
    assert "--heldout-source-ref" in source
    assert "Training complete:      REQUIRED" in source
    assert "Teacher mode:           FROZEN / INFERENCE ONLY" in source


def test_heldout_operator_opens_evaluation_only_without_starting_it() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "Held-out disclosure:    AUTHORIZED FOR EVALUATION ONLY" in source
    assert "Evaluation execution:   NOT STARTED" in source
    assert "teacher_training_authorized" in source
    assert "checkpoint_mutation_authorized" in source
    assert "p2_heldout_animation_evaluation_authorized" in source
    assert "Start-Process" not in source


def test_heldout_operator_keeps_downstream_acceptance_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for field in (
        "human_animated_visual_acceptance_required",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_heldout_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)

def test_heldout_input_operator_uses_source_specific_output_and_safe_ref() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "HeldOutSourceRef -notmatch" in source
    assert "unsafe for the canonical output path" in source
    assert '$outputRoot = Join-Path $heldOutInputRoot $HeldOutSourceRef' in source

