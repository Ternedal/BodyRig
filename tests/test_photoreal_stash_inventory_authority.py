from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _script() -> Path:
    return Path(__file__).resolve().parents[1] / "photoreal-stash-inventory.ps1"


def test_inventory_authority_avoids_powershell_type_coercion() -> None:
    source = _script().read_text(encoding="utf-8")
    assert "Test-NumericV1 -Value $inventory.version" in source
    assert "Test-StrictBoolean -Value $inventory.summary.source_universe_exhaustive -Expected $true" in source
    assert "Test-StrictBoolean -Value $inventory.photoreal_teacher_input -Expected $true" in source
    assert "Test-StrictBoolean -Value $inventory.runtime_dependency -Expected $false" in source
    assert "Test-StrictBoolean -Value $inventory.production_activation -Expected $false" in source
    assert "[int]$inventory.version" not in source
    assert "$inventory.photoreal_teacher_input -ne $true" not in source
    assert "$inventory.runtime_dependency -ne $false" not in source
    assert "$inventory.production_activation -ne $false" not in source


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        (1, True),
        (1.0, True),
        (True, False),
        (False, False),
        ("1", False),
        (2, False),
        (None, False),
        ([], False),
        ({}, False),
    ],
)
def test_inventory_numeric_v1_helper_is_type_faithful(
    version: object, expected: bool, tmp_path: Path
) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not available on this runner")

    script = _script()
    harness = tmp_path / "inventory-numeric-v1.ps1"
    harness.write_text(
        """param([string]$Script,[string]$Json)
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Script, [ref]$tokens, [ref]$errors)
$fn = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-NumericV1' }, $true) | Select-Object -First 1
if ($null -eq $fn) { exit 3 }
Invoke-Expression $fn.Extent.Text
$value = ($Json | ConvertFrom-Json -Depth 20).version
if (Test-NumericV1 -Value $value) { exit 0 }
exit 1
""",
        encoding="utf-8",
    )
    payload = json.dumps({"version": version}, separators=(",", ":"))
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-File", str(harness), str(script), payload],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == (0 if expected else 1), completed.stderr


@pytest.mark.parametrize(
    ("value", "expected_value", "expected"),
    [
        (True, True, True),
        (False, False, True),
        (False, True, False),
        (True, False, False),
        (1, True, False),
        (0, False, False),
        ("true", True, False),
        ("false", False, False),
        (None, False, False),
        ([], False, False),
        ({}, False, False),
    ],
)
def test_inventory_strict_boolean_helper_is_type_faithful(
    value: object, expected_value: bool, expected: bool, tmp_path: Path
) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not available on this runner")

    script = _script()
    harness = tmp_path / "inventory-strict-boolean.ps1"
    harness.write_text(
        """param([string]$Script,[string]$Json,[string]$ExpectedText)
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Script, [ref]$tokens, [ref]$errors)
$fn = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-StrictBoolean' }, $true) | Select-Object -First 1
if ($null -eq $fn) { exit 3 }
Invoke-Expression $fn.Extent.Text
$value = ($Json | ConvertFrom-Json -Depth 20).value
$expected = $ExpectedText -ceq 'true'
if (Test-StrictBoolean -Value $value -Expected $expected) { exit 0 }
exit 1
""",
        encoding="utf-8",
    )
    payload = json.dumps({"value": value}, separators=(",", ":"))
    completed = subprocess.run(
        [
            pwsh,
            "-NoLogo",
            "-NoProfile",
            "-File",
            str(harness),
            str(script),
            payload,
            "true" if expected_value else "false",
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == (0 if expected else 1), completed.stderr
