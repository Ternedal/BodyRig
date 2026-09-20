from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
OPERATOR = ROOT / "diagnose-photoreal-v2-identity-recognizer-ab.ps1"
SETUP = ROOT / "setup-photoreal-v2-identity-recognizer-diagnostic.ps1"


def test_recognizer_ab_operator_is_diagnostic_only_and_avoids_source_rehash() -> None:
    source = OPERATOR.read_text(encoding="utf-8")

    assert "IDENTITY RECOGNIZER A/B DIAGNOSTIC" in source
    assert "buffalo_l / w600k_r50" in source
    assert "antelopev2 / glintr100" in source
    assert "Source rehash:  NO" in source
    assert "identity-extractor\\request.json" in source
    assert "identity-calibration-extractor\\request.json" in source
    assert (
        "identity-calibration-extractor\\output\\negative-observations.json"
        in source
    )
    assert "--identity-request-origin" in source
    assert "--calibration-request-origin" in source
    assert "--negative-observations" in source
    assert "--diagnostic-recognizer-root" in source
    assert "DIAGNOSTIC ONLY / FALSE" in source
    assert (
        "no identity matching, training, photoreal or production authority"
        in source
    )
    assert "import base64" in source
    assert "[Convert]::FromBase64String($encoded)" in source


def test_recognizer_setup_pins_official_antelopev2_bytes() -> None:
    source = SETUP.read_text(encoding="utf-8")

    assert (
        "8e182f14fc6e80b3bfa375b33eb6cff7ee05d8ef7633e738d1c89021dcf0c5c5"
        in source
    )
    assert (
        "4ab1d6435d639628a6f3e5008dd4f929edf4c4124b1a7169e1048f9fef534cdf"
        in source
    )
    assert "glintr100.onnx" in source
    assert "diagnostic-recognizers\\antelopev2" in source
    assert "license_operator_accepted = $true" in source
    assert "diagnostic_only = $true" in source
    assert "identity_matching_authorized = $false" in source
    assert "teacher_training_authorized = $false" in source
    assert "photoreal_acceptance_authority = $false" in source
    assert "production_activation = $false" in source


@pytest.mark.parametrize(
    "script",
    [OPERATOR, SETUP],
)
def test_recognizer_scripts_parse_when_pwsh_available(script: Path) -> None:
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
