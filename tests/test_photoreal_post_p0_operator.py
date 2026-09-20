from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "continue-photoreal-v2-teacher.ps1"


def test_post_p0_operator_requires_clean_main_and_exact_readiness() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'rev-parse --abbrev-ref HEAD' in source
    assert 'requires the main branch' in source
    assert 'status --porcelain' in source
    assert 'requires an exact clean BodyRig checkout' in source
    assert 'review-tools\\VERIFY_PHYSICAL_P0_READY.ps1' in source
    assert 'P0_DOWNSTREAM_READINESS.json' in source
    assert '-ExpectedBodyRigRevision' in source
    assert '-ExpectedPerformerId' in source


def test_post_p0_operator_never_auto_approves_human_review() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '[switch]$ApproveHumanReview' in source
    assert 'if ($ApproveHumanReview)' in source
    assert '"--approve-human-review"' in source
    assert '-SelectedEpochId (a human-assigned audit label for the coherent appearance state) is required with -ApproveHumanReview' in source
    assert 'SelectedEpochId is a human-assigned audit label for the coherent appearance state; it is not a machine-ranked candidate.' in source
    assert 'At least one -SourceGroup is required with -ApproveHumanReview' in source
    assert '-ReviewedBy is required with -ApproveHumanReview' in source
    assert '-ReviewNotes is required with -ApproveHumanReview' in source
    assert 'HUMAN REVIEW REQUIRED' in source
    assert 'Photoreal acceptance: FALSE' in source
    assert 'Production activation: FALSE' in source


def test_post_p0_operator_runs_core_module_from_checkout() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'bodyrig.photoreal_post_p0_continuation_cli' in source
    assert '[Environment]::SetEnvironmentVariable("PYTHONPATH", $newPythonPath, "Process")' in source
    assert '"--p0-root", $P0Root' in source
    assert '"--readiness", $readinessPath' in source
    assert '"--work-root", $WorkRoot' in source
    assert '$code -notin @(0, 2)' in source


def test_post_p0_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return

    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
