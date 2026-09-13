from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-one-command-production-activation.ps1"


def test_one_command_release_uses_bool_safe_numeric_v2_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "function Test-V2Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]2" in source
    assert "Test-V2Version $release.version" in source
    assert "[int]$release.version" not in source


def test_one_command_release_preserves_terminal_pass_bindings() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for boundary in (
        '[string]$release.format -ne "bodyrig-release-acceptance"',
        '$release.release_gate_pass -ne $true',
        '$release.production_activation -ne $true',
        '([string]$release.bodyrig_revision).ToLowerInvariant() -ne $head',
        'release_receipt = $finalReceipt',
        'production_activation = $true',
    ):
        assert boundary in source


def test_one_command_release_v2_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    path = str(SCRIPT.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {{ exit 20 }}
$fn = $ast.Find({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-V2Version' }}, $true)
if ($null -eq $fn) {{ exit 21 }}
Invoke-Expression $fn.Extent.Text
if (-not (Test-V2Version 2)) {{ exit 31 }}
if (-not (Test-V2Version 2.0)) {{ exit 32 }}
if (Test-V2Version $true) {{ exit 33 }}
if (Test-V2Version $false) {{ exit 34 }}
if (Test-V2Version '2') {{ exit 35 }}
if (Test-V2Version $null) {{ exit 36 }}
if (Test-V2Version 1) {{ exit 37 }}
exit 0
"""
    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
