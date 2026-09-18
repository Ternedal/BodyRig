from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "resume-photoreal-v2-after-source.ps1"


def test_resume_runs_nonfatal_diagnostic_only_after_stage13_block() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert (
        '$CalibrationDiagnosticPath = Join-Path $OutputRoot '
        '"identity-calibration-diagnostic.json"'
    ) in text
    assert (
        '"=== 13D/16 DIAGNOSE IDENTITY CALIBRATION BLOCK ==="'
    ) in text
    assert (
        "-m bodyrig.photoreal_identity_calibration_diagnostic_cli"
    ) in text
    assert (
        "WARNING: calibration diagnostic failed; authoritative "
        "Stage 13 block is unchanged."
    ) in text

    diagnostic_block = text[
        text.index('"=== 13D/16 DIAGNOSE IDENTITY CALIBRATION BLOCK ==="'):
        text.index(
            'Write-Status -Status "identity-calibration-blocked"',
            text.index('"=== 13D/16 DIAGNOSE IDENTITY CALIBRATION BLOCK ==="'),
        )
    ]
    assert "2>&1" not in diagnostic_block

    diagnostic_index = text.index(
        '"=== 13D/16 DIAGNOSE IDENTITY CALIBRATION BLOCK ==="'
    )
    blocked_index = text.index(
        'Write-Status -Status "identity-calibration-blocked"'
    )
    exit_index = text.index(
        "exit $finalExitCode",
        blocked_index,
    )

    assert diagnostic_index < blocked_index < exit_index


def test_resume_status_exposes_diagnostic_output_without_authority() -> None:
    text = SCRIPT.read_text(encoding="utf-8-sig")

    assert (
        "identity_calibration_diagnostic = "
        "$script:CalibrationDiagnosticPath"
    ) in text
    assert (
        'Write-Status -Status "identity-calibration-blocked" '
        '-TeacherTrainingAuthorized $false'
    ) in text
