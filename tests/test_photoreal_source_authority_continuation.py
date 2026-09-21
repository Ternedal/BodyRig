from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = (ROOT / "run-photoreal-p0-windows.ps1", ROOT / "resume-photoreal-v2-after-source.ps1")


@pytest.mark.parametrize("script", SCRIPTS)
def test_uncalibrated_identity_does_not_preempt_source_authority(script: Path) -> None:
    source = script.read_text(encoding="utf-8")
    calibration = source.index("if ($calibrationExit -eq 2)")
    frame_measure = source.index("14/16 MEASURE ALL PLANNED FRAMES", calibration)
    frame_authority = source.index("15/16 APPLY CORE IDENTITY AUTHORITY", frame_measure)
    frame_index = source.index("16/16 LEAKAGE + HELD-OUT COVERAGE GATE", frame_authority)
    block = source[calibration:frame_measure]
    assert "exit 2" not in block
    assert 'Write-Status -Status "identity-calibration-blocked"' not in block
    assert "Source-bound identity: CONTINUING" in block
    assert "single-performer Stash sources are independently authorized by source binding" in block
    assert "Ambiguous/multi-person frames remain unresolved without calibrated matching" in block
    assert calibration < frame_measure < frame_authority < frame_index


@pytest.mark.parametrize("script", SCRIPTS)
def test_calibration_evidence_still_flows_into_core_authority(script: Path) -> None:
    source = script.read_text(encoding="utf-8")
    assert "13/16 DERIVE IDENTITY THRESHOLD" in source
    assert "AllowedExitCodes @(0, 2)" in source
    assert '$calibration = Read-Json -Path $CalibrationPath -Label "Identity calibration"' in source
    assert "$calibration.calibration_blockers" in source
    assert '"--identity-calibration", $CalibrationPath' in source


@pytest.mark.parametrize("script", SCRIPTS)
def test_source_authority_wrappers_parse_when_pwsh_available(script: Path) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")
    command = (
        "$tokens=$null; $errors=$null; "
        "$null=[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:BODYRIG_PARSE_SCRIPT,[ref]$tokens,[ref]$errors); "
        "if ($errors.Count -ne 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }; exit 0"
    )
    env = os.environ.copy()
    env["BODYRIG_PARSE_SCRIPT"] = str(script)
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-Command", command],
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env
    )
    assert completed.returncode == 0, completed.stderr
