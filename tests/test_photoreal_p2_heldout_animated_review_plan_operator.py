from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p2-heldout-animated-review-plan.ps1"


def test_review_plan_operator_requires_clean_main() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source


def test_review_plan_operator_resolves_only_selected_source_workspaces() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "held_out_source_ref" in source
    assert "Sort-Object -Unique" in source
    assert "animation-evaluation\\heldout-execution" in source
    assert "--evaluation-workspace" in source
    assert "unsafe for the canonical evaluation path" in source


def test_review_plan_operator_cannot_complete_human_acceptance() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for field in (
        "held_out_evaluation_only",
        "evaluation_artifact_bytes_reverified",
        "human_animated_visual_acceptance_required",
        "human_animated_review_complete",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source


def test_review_plan_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
