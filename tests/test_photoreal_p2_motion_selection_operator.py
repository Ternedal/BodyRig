from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "record-photoreal-v2-p2-motion-selection.ps1"


def test_p2_motion_selection_operator_requires_clean_main_and_bound_inputs() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert 'Join-Path $handoffRoot "p2-motion-evidence-handoff.json"' in source
    assert 'Join-Path $handoffRoot "private-motion-source-index.json"' in source
    assert 'Join-Path $P2Root "p2-motion-source-selection.json"' in source


def test_p2_motion_selection_operator_preserves_explicit_human_gate() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "HUMAN REVIEW REQUIRED: select at least one TRAIN driver" in source
    assert "$ApproveHumanSelection" in source
    assert "-ApproveHumanSelection" in source
    assert "exit 2" in source
    assert "MotionDriverSourceRef" in source
    assert "HeldOutValidationSourceRef" in source


def test_p2_motion_selection_operator_never_rehashes_or_starts_animation() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "Source media rehash:  NO" in source
    assert "No source was rehashed and no animation was started." in source
    assert "Get-FileHash" not in source
    assert "Start-Process" not in source


def test_p2_motion_selection_operator_grants_input_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for field in (
        "motion_source_selection_authority",
        "p2_motion_input_authorized",
        "p2_animation_execution_authorized",
        "p2_animated_teacher_acceptance_authority",
        "quest_distillation_authorized",
        "photoreal_acceptance_authority",
        "production_activation",
    ):
        assert field in source
    assert "Motion-input preparation:   AUTHORIZED" in source
    assert "Animation execution:        FALSE" in source


def test_p2_motion_selection_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return

    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
