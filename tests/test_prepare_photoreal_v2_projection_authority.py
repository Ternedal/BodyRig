from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "prepare-photoreal-v2-projection-authority.ps1"


def test_helper_requires_explicit_operator_attestation_without_parameter_prompt() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$ConfirmVr180Equi" in source
    assert '[Parameter(Mandatory = $true)][switch]$ConfirmVr180Equi' not in source
    assert 'if (-not $ConfirmVr180Equi)' in source
    assert "explicit -ConfirmVr180Equi operator attestation" in source


def test_helper_uses_only_sha_bound_run_artifacts() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'Join-Path $RunDirectory "dataset-plan.json"' in source
    assert 'Join-Path $RunDirectory "source-receipt.json"' in source
    assert "bodyrig.photoreal_explicit_projection_authority_cli" in source
    assert "--operator-verified-vr180-equi" in source
    assert "--stereo-layout $StereoLayout" in source
    assert "--plan $planPath" in source
    assert "--receipt $receiptPath" in source


def test_helper_never_enables_runtime_or_production_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'Write-Host "Production:      FALSE"' in source
    assert "production_activation = $true" not in source
    assert "-Production" not in source


def test_helper_outputs_path_for_overnight_projection_authority_parameter() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert 'Write-Host "Use with: -ProjectionAuthority `"$resolvedOutput`""' in source
    assert 'BodyRig\\photoreal-v2\\projection-authority' in source


def test_helper_powershell_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not available on this runner")

    command = (
        "$tokens=$null; $errors=$null; "
        "$null=[System.Management.Automation.Language.Parser]::ParseFile($env:BODYRIG_PARSE_SCRIPT,[ref]$tokens,[ref]$errors); "
        "if ($errors.Count -ne 0) { $errors | ForEach-Object { Write-Error $_ }; exit 1 }; exit 0"
    )
    env = os.environ.copy()
    env["BODYRIG_PARSE_SCRIPT"] = str(SCRIPT)
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-Command", command],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert completed.returncode == 0, completed.stderr
