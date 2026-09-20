from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OPERATOR = ROOT / "diagnose-photoreal-v2-temporal-person-consistency.ps1"


def test_temporal_consistency_operator_is_non_biometric_and_fail_closed() -> None:
    source = OPERATOR.read_text(encoding="utf-8")

    assert "TEMPORAL PERSON CONSISTENCY" in source
    assert "Face matching:  NO" in source
    assert "Face embedding: NO" in source
    assert "Source rehash:  NO" in source
    assert "DIAGNOSTIC ONLY / FALSE" in source
    assert "no biometric identity matching or production authority" in source
    assert "photoreal_temporal_person_consistency_diagnostic.py" in source
    assert "identity-extractor\\request.json" in source
    assert "identity-calibration-extractor\\request.json" in source
    assert "negative-observations.json" in source
    assert "BODYRIG_REVISION=$head" in source


@pytest.mark.parametrize("script", [OPERATOR])
def test_temporal_consistency_operator_parses_when_pwsh_available(
    script: Path,
) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not available on this runner")
    command = (
        "$tokens=$null; $errors=$null; "
        "$null=[System.Management.Automation.Language.Parser]::ParseFile("
        "$env:BODYRIG_PARSE_SCRIPT,[ref]$tokens,[ref]$errors); "
        "if ($errors.Count -ne 0) { "
        "$errors | ForEach-Object { Write-Error $_ }; exit 1 }; exit 0"
    )
    env = os.environ.copy()
    env["BODYRIG_PARSE_SCRIPT"] = str(script)
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-Command", command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
