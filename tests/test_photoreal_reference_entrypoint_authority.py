from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _entrypoint() -> Path:
    return Path(__file__).resolve().parents[1] / "start-photoreal-v2-reference.ps1"


def test_reference_entrypoint_fails_fast_on_output_root_and_api_key_before_setup() -> None:
    source = _entrypoint().read_text(encoding="utf-8")
    output_guard = source.index('if (Test-Path -LiteralPath $OutputRoot)')
    api_guard = source.index('[Environment]::GetEnvironmentVariable($ApiKeyEnv)')
    model_setup_gate = source.index('$modelReady =')
    runtime_setup_gate = source.index('$runtimeReady =')

    assert output_guard < model_setup_gate
    assert api_guard < model_setup_gate
    assert output_guard < runtime_setup_gate
    assert api_guard < runtime_setup_gate
    assert "Use a new empty output root for every P0 attempt" in source


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
def test_one_command_powershell_strict_boolean_gate(value: object, expected_value: bool, expected: bool, tmp_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not available on this runner")

    entrypoint = _entrypoint()
    source = entrypoint.read_text(encoding="utf-8")
    assert "Test-StrictBoolean -Value $receipt.build_only -Expected $true" in source
    assert "Test-StrictBoolean -Value $receipt.production_activation -Expected $false" in source

    harness = tmp_path / "strict-boolean-harness.ps1"
    harness.write_text(
        """param([string]$Entrypoint,[string]$Json)
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile($Entrypoint, [ref]$tokens, [ref]$errors)
$fn = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-StrictBoolean' }, $true) | Select-Object -First 1
if ($null -eq $fn) { exit 3 }
Invoke-Expression $fn.Extent.Text
$payload = $Json | ConvertFrom-Json -Depth 20
if (Test-StrictBoolean -Value $payload.value -Expected $payload.expected_value) { exit 0 }
exit 1
""",
        encoding="utf-8",
    )
    payload = json.dumps({"value": value, "expected_value": expected_value}, separators=(",", ":"))
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-File", str(harness), str(entrypoint), payload],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == (0 if expected else 1), completed.stderr
