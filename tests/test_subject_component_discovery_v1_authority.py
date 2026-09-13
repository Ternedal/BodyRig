from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-subject-component-discovery.ps1"


V1_READERS = (
    "$summary.version",
    "$packageResult.version",
    "$workspaceReceipt.version",
    "$candidateReconstructionAuthority.version",
    "$refit.version",
    "$candidateAudit.version",
    "$hair.version",
    "$eyes.version",
    "$eyeAppearance.version",
    "$runtime.version",
)


def test_subject_component_discovery_uses_bool_safe_numeric_v1_everywhere() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source

    for reader in V1_READERS:
        assert f"Test-V1Version {reader}" in source
        assert f"[int]{reader}" not in source


def test_subject_component_discovery_preserves_active_authority_boundaries() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for boundary in (
        'bodyrig-subject-anatomy-physical-gate',
        'bodyrig-subject-anatomy-candidate-result',
        'bodyrig-subject-anatomy-workspace',
        'bodyrig-sith-reconstruction-authority',
        'bodyrig-subject-anatomy-refit',
        'bodyrig-anatomy-geometry-audit',
        'bodyrig-source-hair-candidate',
        'bodyrig-eye-component-candidate',
        'bodyrig-eye-appearance-candidate',
        'bodyrig-source-hair-eye-review-runtime',
        '[string]$summary.bodyrig_revision -ne $head',
        '[string]$summary.package_sha256 -ne $packageSha',
        '[string]$packageResult.package_sha256 -ne $packageSha',
        '[string]$candidateReconstructionAuthority.reconstruction_sha256 -ne $candidateReconstructionSha',
        '[string]$refit.derivedSmplxObjSha256 -ne $donorSha',
        '[string]$candidateAudit.donorObjSha256 -ne $donorSha',
        '[string]$hair.sourceReconstructionSha256 -ne $candidateReconstructionSha',
        '[string]$eyeAppearance.sourceReconstructionSha256 -ne $candidateReconstructionSha',
        '[string]$runtime.packageSha256 -ne $packageSha',
        '$runtime.comparisonOnly -ne $true',
        '$runtime.humanReviewRequired -ne $true',
        '$runtime.productionActivation -ne $false',
        'high_fidelity_ready = $false',
        'production_activation = $false',
    ):
        assert boundary in source


def test_subject_component_discovery_v1_guard_runtime_semantics() -> None:
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
