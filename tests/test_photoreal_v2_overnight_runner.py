from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "start-photoreal-v2-overnight.ps1"


def test_overnight_success_requires_persisted_authorized_p0_status() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    verify = source.index("$p0Status = Read-AuthorizedP0Status")
    bind_digest = source.index("Get-FileHash -LiteralPath $p0StatusPath -Algorithm SHA256")
    completed = source.index('$summary.status = "completed"')

    assert verify < bind_digest < completed
    assert 'status.status -ne "teacher-training-authorized"' in source
    assert "Test-StrictBoolean -Value $status.teacher_training_authorized -Expected $true" in source
    assert "@($status.blockers).Count -ne 0" in source
    assert "Test-StrictBoolean -Value $status.human_visual_acceptance_required -Expected $true" in source
    assert "Test-StrictBoolean -Value $status.photoreal_acceptance_authority -Expected $false" in source
    assert "Test-StrictBoolean -Value $status.production_activation -Expected $false" in source


def test_overnight_summary_binds_p0_without_crossing_downstream_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "p0_status_sha256 = $null" in source
    assert "bodyrig_revision = $null" in source
    assert "teacher_training_authorized = $false" in source
    assert "human_visual_acceptance_required = $true" in source
    assert "photoreal_acceptance_authority = $false" in source
    assert "production_activation = $false" in source
    assert "$summary.p0_status_sha256 = $statusHash" in source
    assert "$summary.bodyrig_revision = [string]$p0Status.bodyrig_revision" in source
    assert "$summary.teacher_training_authorized = $true" in source
    assert "$summary.photoreal_acceptance_authority = $true" not in source
    assert "$summary.production_activation = $true" not in source


def test_overnight_runner_rejects_nonzero_entrypoint_before_success() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    invoke = source.index("& $entrypoint @args")
    exit_guard = source.index("$entrypointExit = $LASTEXITCODE")
    authority = source.index("$p0Status = Read-AuthorizedP0Status")
    completed = source.index('$summary.status = "completed"')

    assert invoke < exit_guard < authority < completed
    assert "$entrypointExit -ne 0" in source


def test_overnight_forwards_reference_environment_repair() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "[switch]$RepairReferenceEnvironment" in source
    assert "if ($RepairReferenceEnvironment) { $args.RepairReferenceEnvironment = $true }" in source


def test_overnight_restores_saved_stash_auth_without_persisting_secret() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "function Restore-SavedStashCredential" in source
    assert 'Join-Path $env:LOCALAPPDATA "BodyRig\\config\\stash.json"' in source
    assert 'config.format -ne "bodyrig-local-stash-config"' in source
    assert "ConvertTo-SecureString ([string]$config.api_key_dpapi)" in source
    assert "SecureStringToBSTR" in source
    assert "PtrToStringBSTR" in source
    assert '[Environment]::SetEnvironmentVariable($EnvironmentName, $apiKey, "Process")' in source
    assert '[Environment]::SetEnvironmentVariable($ApiKeyEnv, $originalApiKey, "Process")' in source
    assert "api_key_dpapi" not in source[source.index("$summary = [ordered]@{"):source.index("$summary | ConvertTo-Json")]


def test_overnight_surfaces_failure_message_to_operator() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert '$summary.error = $_.Exception.Message' in source
    assert 'Write-Host "Error: $($summary.error)"' in source


def test_overnight_powershell_parses_when_pwsh_is_available() -> None:
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
