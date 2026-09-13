from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ROOT / "verify-repository-authority.ps1"
SCRIPT = SCRIPT_PATH.read_text(encoding="utf-8")


def test_wrapper_is_clean_main_and_checkout_bound() -> None:
    assert 'branch --show-current' in SCRIPT
    assert 'status --porcelain' in SCRIPT
    assert 'rev-parse HEAD' in SCRIPT
    assert 'bodyrig.repository_authority' in SCRIPT
    assert 'repository_authority.py' in SCRIPT
    assert 'imported from wrong checkout' in SCRIPT
    assert '--expected-head' in SCRIPT


def test_wrapper_reads_live_github_repository_authority() -> None:
    assert 'gh auth status -h github.com' in SCRIPT
    assert 'repos/Ternedal/BodyRig/branches/main' in SCRIPT
    assert 'repos/Ternedal/BodyRig/branches/main/protection' in SCRIPT
    assert 'repos/Ternedal/BodyRig/rulesets?includes_parents=true' in SCRIPT
    assert 'repos/Ternedal/BodyRig/rulesets/$id' in SCRIPT


def test_wrapper_is_read_only_and_non_physical() -> None:
    assert 'gh api' in SCRIPT
    assert 'gh api --method' not in SCRIPT
    assert 'physical acceptance or production activation' in SCRIPT
    assert 'exit 2' in SCRIPT
    assert 'BodyRig repository authority:' in SCRIPT


def test_wrapper_uses_bool_safe_numeric_v1() -> None:
    assert "function Test-V1Version($Value)" in SCRIPT
    assert "$Value -is [bool]" in SCRIPT
    assert "$Value -isnot [ValueType]" in SCRIPT
    assert "[decimal]$Value -eq [decimal]1" in SCRIPT
    assert "Test-V1Version $result.version" in SCRIPT
    assert "[int]$result.version" not in SCRIPT
    assert '$result.passed -ne $true' in SCRIPT


def test_repository_authority_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    script_path = str(SCRIPT_PATH.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{script_path}', [ref]$tokens, [ref]$errors)
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
