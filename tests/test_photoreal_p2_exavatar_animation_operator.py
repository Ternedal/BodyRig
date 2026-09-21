from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-photoreal-v2-p2-exavatar-animation.ps1"


def test_animation_operator_requires_clean_main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source


def test_animation_operator_consumes_only_authorized_surfaces() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "p2-exavatar-animation-execution-input.json" in source
    assert "exavatar-teacher-config.json" in source
    assert "photoreal_p2_exavatar_animation_adapter.py" in source
    assert "motion-preparation\\output" in source
    assert "animation-input\\exavatar-identity" in source


def test_animation_operator_is_explicit_about_first_real_execution() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "WILL start pinned ExAvatar animation" in source
    assert "Human P2 acceptance:  REQUIRED AFTER THIS RUN" in source
    assert "Held-out disclosure:  FALSE" in source
    assert "Source-media rehash:  NO" in source


def test_animation_operator_keeps_downstream_authority_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for field in (
        "artifact_bytes_verified_by_core",
        "animation_complete",
        "inference_only",
        "teacher_training_performed",
        "checkpoint_mutation_performed",
        "human_animated_visual_acceptance_required",
        "held_out_evaluation_disclosed",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_animation_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
