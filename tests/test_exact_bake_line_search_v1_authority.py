from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "line-search-exact-anatomy-bake.ps1"


def test_line_search_uses_bool_safe_numeric_v1() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source
    assert "Test-V1Version $evidence.version" in source
    assert "[int]$evidence.version" not in source


def test_line_search_preserves_exact_bake_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for boundary in (
        'bodyrig-subject-anatomy-exact-bake-line-search',
        'Exact-bake anatomy line search changed retained or endpoint authority bytes',
        '$evidence.exactProductionBakePath -ne $true',
        '$evidence.comparisonOnly -ne $true',
        '$evidence.humanReviewRequired -ne $true',
        '$evidence.humanFidelityPass -ne $false',
        '$evidence.productionReady -ne $false',
        '$evidence.reconstructionRerun -ne $false',
        '[string]$evidence.retainedSmplxObjSha256 -ne $before[$retainedDonor]',
        '[string]$evidence.endpointSmplxObjSha256 -ne $before[$endpointDonor]',
        'exact 1024x1024 production anatomy bake',
        'PASS (comparison only)',
        'Human review:   REQUIRED',
        'Production:     FALSE',
        'SiTH rerun:     FALSE',
    ):
        assert boundary in source


def test_line_search_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    script_path = str(SCRIPT.resolve()).replace("'", "''")
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
