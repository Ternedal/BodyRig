from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _runner() -> Path:
    return Path(__file__).resolve().parents[1] / "run-photoreal-p0-windows.ps1"


def test_final_p0_authority_uses_strict_boolean_gate() -> None:
    source = _runner().read_text(encoding="utf-8")
    assert "function Test-StrictBoolean" in source
    assert (
        "$trainingAuthorized = ($indexExit -eq 0 -and "
        "(Test-StrictBoolean -Value $frameIndex.teacher_training_authorized -Expected $true))"
    ) in source
    assert "$frameIndex.teacher_training_authorized -eq $true" not in source


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (1, False),
        (0, False),
        ("true", False),
        ("false", False),
        (None, False),
        ([], False),
        ({}, False),
    ],
)
def test_final_p0_powershell_boolean_gate_is_type_faithful(
    value: object, expected: bool, tmp_path: Path
) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is not available on this runner")

    runner = _runner()
    harness = tmp_path / "p0-final-authority-boolean.ps1"
    harness.write_text(
        """param([string]$Runner,[string]$Json)\n"
        "$tokens = $null\n"
        "$errors = $null\n"
        "$ast = [System.Management.Automation.Language.Parser]::ParseFile($Runner, [ref]$tokens, [ref]$errors)\n"
        "$fn = $ast.FindAll({ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq 'Test-StrictBoolean' }, $true) | Select-Object -First 1\n"
        "if ($null -eq $fn) { exit 3 }\n"
        "Invoke-Expression $fn.Extent.Text\n"
        "$value = ($Json | ConvertFrom-Json -Depth 20).value\n"
        "if (Test-StrictBoolean -Value $value -Expected $true) { exit 0 }\n"
        "exit 1\n"
        """,
        encoding="utf-8",
    )
    payload = json.dumps({"value": value}, separators=(",", ":"))
    completed = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-File", str(harness), str(runner), payload],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert completed.returncode == (0 if expected else 1), completed.stderr
