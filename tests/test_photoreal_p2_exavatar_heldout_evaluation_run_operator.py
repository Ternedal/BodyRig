from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-photoreal-v2-p2-exavatar-heldout-evaluation.ps1"


def test_heldout_run_operator_requires_clean_main_and_safe_source_ref() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert "HeldOutSourceRef -notmatch" in source
    assert "unsafe for the canonical workspace path" in source


def test_heldout_run_operator_uses_source_specific_input_and_workspace() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'animation-evaluation\\heldout-input' in source
    assert 'animation-evaluation\\heldout-execution' in source
    assert "$HeldOutSourceRef" in source
    assert "heldout-evaluation-execution-receipt.json" in source


def test_heldout_run_operator_is_inference_only_and_non_accepting() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "INFERENCE ONLY / HELD-OUT" in source
    assert "post-training-inference-only-evaluation" in source
    for field in (
        "artifact_bytes_verified_by_core",
        "evaluation_complete",
        "inference_only",
        "held_out_evaluation_disclosed",
        "human_animated_visual_acceptance_required",
        "teacher_training_performed",
        "checkpoint_mutation_performed",
        "source_media_rehash_performed",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_heldout_run_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
