from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-one-command-production-activation.ps1"


def test_one_command_recovery_uses_bool_safe_numeric_v1_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source
    assert 'Test-V1Version $plan.version' in source
    assert '[int]$plan.version' not in source


def test_one_command_recovery_preserves_exact_authority_bindings() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for boundary in (
        'bodyrig.interrupted_fit_recovery plan',
        '[string]$plan.format -ne "bodyrig-interrupted-fit-recovery-plan"',
        '([string]$plan.bodyrig_revision).ToLowerInvariant() -ne $head',
        '[string]$plan.performer_id -ne $PerformerId',
        '[string]$plan.body_alias -ne $BodyId',
        '$matches.Count -eq 1',
        '$authority["interrupted_fit_recovery_plan_sha256"] = $planHash',
        '$authority["expensive_reconstruction_rerun"] = $false',
        'production_activation = $false',
    ):
        assert boundary in source


def test_one_command_recovery_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    path = str(SCRIPT.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {{ exit 20 }}
$fn = $ast.Find({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-V1Version' }}, $true)
if ($null -eq $fn) {{ exit 21 }}
Invoke-Expression $fn.Extent.Text
if (-not (Test-V1Version 1)) {{ exit 31 }}
if (-not (Test-V1Version 1.0)) {{ exit 32 }}
if (Test-V1Version $true) {{ exit 33 }}
if (Test-V1Version $false) {{ exit 34 }}
if (Test-V1Version '1') {{ exit 35 }}
if (Test-V1Version $null) {{ exit 36 }}
if (Test-V1Version 2) {{ exit 37 }}
exit 0
"""
    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
