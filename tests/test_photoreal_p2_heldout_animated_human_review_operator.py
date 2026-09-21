from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "prepare-photoreal-v2-p2-heldout-animated-human-review.ps1"
RECORD = ROOT / "record-photoreal-v2-p2-heldout-animated-human-review.ps1"


def test_prepare_operator_cannot_record_acceptance() -> None:
    source = PREPARE.read_text(encoding="utf-8")
    assert '"prepare"' in source
    assert '"record"' not in source
    assert "Human decisions:       NOT RECORDED" in source
    assert "p2_animated_teacher_acceptance_authority" in source
    assert "p3_device_distillation_authorized" in source
    assert "Start-Process $reviewIndex" in source


def test_record_operator_requires_explicit_confirmation_and_decisions() -> None:
    source = RECORD.read_text(encoding="utf-8")
    assert "ConfirmReviewComplete" in source
    assert "Explicit -ConfirmReviewComplete is required" in source
    assert "--decision" in source
    assert "--quality-check" in source
    assert "--confirm-review-complete" in source


def test_record_operator_preserves_pass_fail_semantics_without_production() -> None:
    source = RECORD.read_text(encoding="utf-8")
    assert '$status -eq "pass"' in source
    assert '$status -eq "fail"' in source
    assert "p3_device_distillation_authorized" in source
    assert "production_activation" in source
    assert "photoreal_acceptance_authority" in source


def test_human_review_operators_parse_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    for script in (PREPARE, RECORD):
        command = (
            "$tokens=$null; $errors=$null; "
            f"[System.Management.Automation.Language.Parser]::ParseFile('{script.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
            "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
        )
        subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
