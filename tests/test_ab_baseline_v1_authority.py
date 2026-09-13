from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PREFLIGHT = ROOT / "preflight-ab-baseline.ps1"


def test_ab_baseline_preflight_uses_bool_safe_numeric_v1_authority() -> None:
    source = PREFLIGHT.read_text(encoding="utf-8")
    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source
    assert "Test-V1Version $result.version" in source
    assert "Test-V1Version $physical.version" in source
    assert "[int]$result.version" not in source
    assert "[int]$physical.version" not in source


def test_ab_baseline_preflight_preserves_non_activating_authority_boundaries() -> None:
    source = PREFLIGHT.read_text(encoding="utf-8")
    for boundary in (
        "$result.comparison_only -ne $true",
        "$result.human_visual_authority_required -ne $true",
        "$result.physical_acceptance_authority -ne $false",
        "$result.promotion_authority -ne $false",
        "$result.production_activation -ne $false",
        "$physical.physical_acceptance_authority -ne $false",
        "$physical.promotion_authority -ne $false",
        "$physical.production_activation -ne $false",
    ):
        assert boundary in source


def test_ab_baseline_preflight_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    path = str(PREFLIGHT.resolve()).replace("'", "''")
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
