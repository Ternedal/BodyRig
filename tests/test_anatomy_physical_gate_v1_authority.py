from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FAMILY = ROOT / "audit-retained-smplx-family.ps1"
REFIT = ROOT / "refit-subject-anatomy.ps1"
GATE = ROOT / "run-subject-anatomy-physical-gate.ps1"
WRAPPERS = (FAMILY, REFIT)


def test_active_physical_gate_wires_hardened_wrappers() -> None:
    source = GATE.read_text(encoding="utf-8")
    assert 'audit-retained-smplx-family.ps1' in source
    assert 'refit-subject-anatomy.ps1' in source
    assert '$familyScript = Need-File' in source
    assert '$refitScript = Need-File' in source
    assert 'Invoke-GateScript -Script $familyScript' in source
    assert 'Invoke-GateScript -Script $refitScript' in source
    assert '$buildScript = Need-File' in source


def test_active_anatomy_wrappers_use_bool_safe_numeric_v1() -> None:
    for path in WRAPPERS:
        source = path.read_text(encoding="utf-8")
        assert "function Test-V1Version($Value)" in source
        assert "$Value -is [bool]" in source
        assert "$Value -isnot [ValueType]" in source
        assert "[decimal]$Value -eq [decimal]1" in source
        assert "Test-V1Version $evidence.version" in source
        assert "[int]$evidence.version" not in source


def test_family_audit_preserves_retained_authority() -> None:
    source = FAMILY.read_text(encoding="utf-8")
    for boundary in (
        'bodyrig-reconstruction-smplx-family-audit',
        '[string]$evidence.retainedSmplxObjSha256 -ne $smplxSha',
        '[string]$evidence.retainedFitParamsSha256 -ne $fitSha',
        '$evidence.reconstructionRerun -ne $false',
        '$evidence.geometryModified -ne $false',
        '$evidence.productionReady -ne $false',
        'Retained reconstruction authority changed during SMPL-X family audit.',
        'Human review:   REQUIRED',
        'Production:     FALSE',
        'SiTH rerun:     FALSE',
    ):
        assert boundary in source


def test_refit_preserves_candidate_and_non_regression_authority() -> None:
    source = REFIT.read_text(encoding="utf-8")
    for boundary in (
        'bodyrig-subject-anatomy-refit',
        '[string]$evidence.targetModelFamily -ne $TargetFamily',
        '$evidence.retainedReconstructionModified -ne $false',
        '$evidence.reconstructionRerun -ne $false',
        '$evidence.generativeGeometry -ne $false',
        '$evidence.comparisonOnly -ne $true',
        '$evidence.humanReviewRequired -ne $true',
        '$evidence.productionReady -ne $false',
        '[string]$evidence.derivedSmplxObjSha256 -ne (Sha256 $derivedObj)',
        '[string]$evidence.derivedFitParamsSha256 -ne (Sha256 $derivedFit)',
        '$evidence.fitDidNotRegress -ne $true',
        'CANDIDATE REGRESSED (evidence preserved)',
        'CANDIDATE PASS (comparison only)',
    ):
        assert boundary in source


@pytest.mark.parametrize("path", WRAPPERS)
def test_active_anatomy_v1_guard_runtime_semantics(path: Path) -> None:
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
