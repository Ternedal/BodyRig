from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "hair": ROOT / "extract-retained-hair.ps1",
    "eyes": ROOT / "extract-eye-components.ps1",
}


def test_source_component_wrappers_use_bool_safe_numeric_v1() -> None:
    for path in SCRIPTS.values():
        source = path.read_text(encoding="utf-8")
        assert "function Test-V1Version($Value)" in source
        assert "$Value -is [bool]" in source
        assert "$Value -isnot [ValueType]" in source
        assert "[decimal]$Value -eq [decimal]1" in source
        assert "Test-V1Version $evidence.version" in source
        assert "[int]$evidence.version" not in source


def test_hair_candidate_preserves_source_and_non_activation_boundaries() -> None:
    source = SCRIPTS["hair"].read_text(encoding="utf-8")
    for boundary in (
        '$evidence.sourceDerived -ne $true',
        '$evidence.generativeGeometry -ne $false',
        '$evidence.bodyTopologyModified -ne $false',
        '$evidence.comparisonOnly -ne $true',
        '$evidence.humanReviewRequired -ne $true',
        '$evidence.productionReady -ne $false',
        '[string]$evidence.sourceReconstructionSha256 -ne $reconstructionShaBefore',
        '[string]$evidence.sourceMeshSha256 -ne $sourceShaBefore',
        '[string]$evidence.hairObjSha256 -ne (Sha256 $hairObj)',
        'Retained reconstruction/source bytes changed during hair extraction.',
        'Human review:   REQUIRED',
        'Production:     FALSE',
    ):
        assert boundary in source


def test_eye_candidate_preserves_partial_non_synthetic_authority() -> None:
    source = SCRIPTS["eyes"].read_text(encoding="utf-8")
    for boundary in (
        '$evidence.explicitEyeGeometry -ne $true',
        '$evidence.sourceDerivedIrisAppearance -ne $false',
        '[string]$evidence.componentStatus -ne "partial"',
        '$evidence.bodyTopologyModified -ne $false',
        '$evidence.generativeIdentitySynthesis -ne $false',
        '$evidence.humanReviewRequired -ne $true',
        '$evidence.productionReady -ne $false',
        'Iris:           MISSING',
        'Cornea:         MISSING',
        'Eyelashes:      MISSING',
        'Human review:   REQUIRED',
        'Production:     FALSE',
    ):
        assert boundary in source


@pytest.mark.parametrize("path", tuple(SCRIPTS.values()))
def test_source_component_v1_guard_runtime_semantics(path: Path) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    script_path = str(path.resolve()).replace("'", "''")
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
