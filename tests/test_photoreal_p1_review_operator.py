from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-photoreal-v2-p1-review.ps1"


def test_p1_operator_requires_clean_main_and_exact_teacher_outputs() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "requires the main branch" in source
    assert "requires an exact clean BodyRig checkout" in source
    assert 'Join-Path $teacherWorkspace "output"' in source
    assert 'Join-Path $teacherResultRoot "teacher-manifest.json"' in source
    assert 'Join-Path $AppearanceReviewRoot "appearance-epoch-visual-review-manifest.json"' in source


def test_p1_operator_preserves_three_explicit_human_gates() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "HUMAN REVIEW REQUIRED: semantic camera alignment" in source
    assert "HUMAN REVIEW REQUIRED: P1 held-out evidence pairing" in source
    assert "HUMAN REVIEW REQUIRED: final P1 static-teacher likeness" in source
    assert "$ApproveSemanticReview" in source
    assert "$ApprovePairingReview" in source
    assert "$ConfirmLikenessReview" in source
    assert "--approve-human-review" in source
    assert "--confirm-review-complete" in source


def test_p1_operator_never_auto_approves_or_auto_opens_review() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "& Start-Process" not in source
    assert 'Write-Host (\'  Start-Process "' in source
    assert "if (-not $ApproveSemanticReview)" in source
    assert "if (-not $ApprovePairingReview)" in source
    assert "if (-not $ConfirmLikenessReview)" in source


def test_p1_operator_uses_exact_stacked_contracts() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "bodyrig.photoreal_teacher_semantic_alignment" in source
    assert "bodyrig.photoreal_p1_heldout_pairing" in source
    assert "bodyrig.photoreal_p1_likeness_review" in source
    assert "--teacher-workspace" in source
    assert "--appearance-review-manifest" in source
    assert "--teacher-output-root" in source
    assert "validate_likeness_review_receipt" in source


def test_p1_operator_reports_narrow_p1_authority_only() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "P2 animation:       AUTHORIZED" in source
    assert "P2 animation:       BLOCKED" in source
    assert "Photoreal authority: FALSE" in source
    assert "Production:          FALSE" in source


def test_p1_operator_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return

    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
