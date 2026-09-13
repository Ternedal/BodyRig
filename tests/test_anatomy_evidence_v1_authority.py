from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "refit_v3": ROOT / "refit-subject-anatomy-v3.ps1",
    "retained_audit": ROOT / "audit-retained-anatomy.ps1",
    "candidate_audit": ROOT / "audit-anatomy-candidate.ps1",
    "exact_bake": ROOT / "score-exact-anatomy-bake.ps1",
}


def test_anatomy_wrappers_use_bool_safe_numeric_v1() -> None:
    for path in SCRIPTS.values():
        source = path.read_text(encoding="utf-8")
        assert "function Test-V1Version($Value)" in source
        assert "$Value -is [bool]" in source
        assert "$Value -isnot [ValueType]" in source
        assert "[decimal]$Value -eq [decimal]1" in source
        assert "Test-V1Version $evidence.version" in source
        assert "[int]$evidence.version" not in source


def test_refit_v3_preserves_candidate_and_normal_authority() -> None:
    source = SCRIPTS["refit_v3"].read_text(encoding="utf-8")
    for boundary in (
        'explicit-family-smplx-betas-icp-bake-surface-normal-aware-to-retained-sith-source-v3',
        'sith-closest-source-triangle-face-normal-v1',
        'deterministic-smplx-face-centroids-v1',
        '[int]$evidence.normalSampleCount -lt 100',
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


def test_anatomy_audits_preserve_hash_human_review_and_mismatch_semantics() -> None:
    retained = SCRIPTS["retained_audit"].read_text(encoding="utf-8")
    candidate = SCRIPTS["candidate_audit"].read_text(encoding="utf-8")

    assert '[string]$evidence.donorObjSha256 -ne $donorSha' in retained
    assert '[string]$evidence.sourceObjSha256 -ne $sourceSha' in retained
    assert '$evidence.humanReviewRequired -ne $true' in retained
    assert '$audit.ExitCode -eq 2 -or $evidence.grossAnatomyPass -ne $true' in retained
    assert 'GROSS PASS (human anatomy review still required)' in retained

    assert '[string]$evidence.donorObjSha256 -ne $donorSha' in candidate
    assert '[string]$evidence.sourceObjSha256 -ne $sourceShaBefore' in candidate
    assert '$evidence.humanReviewRequired -ne $true' in candidate
    assert '$audit.ExitCode -eq 2 -or $evidence.grossAnatomyPass -ne $true' in candidate
    assert 'Retained reconstruction/source bytes changed during anatomy candidate audit.' in candidate
    assert 'GROSS PASS (human anatomy review still required)' in candidate


def test_exact_bake_preserves_read_only_diagnostic_authority() -> None:
    source = SCRIPTS["exact_bake"].read_text(encoding="utf-8")
    for boundary in (
        '$evidence.exactProductionBakePath -ne $true',
        '$evidence.comparisonOnly -ne $true',
        '$evidence.humanReviewRequired -ne $true',
        '$evidence.humanFidelityPass -ne $false',
        '$evidence.productionReady -ne $false',
        '$evidence.reconstructionRerun -ne $false',
        '[string]$evidence.donorSha256 -ne $donorShaBefore',
        '[string]$evidence.reconstructionSha256 -ne $reconstructionShaBefore',
        'Read-only exact anatomy bake scoring changed retained or donor bytes.',
        'PASS (diagnostic only)',
        'Human review:   REQUIRED',
        'Production:     FALSE',
    ):
        assert boundary in source


@pytest.mark.parametrize("path", tuple(SCRIPTS.values()))
def test_anatomy_v1_guard_runtime_semantics(path: Path) -> None:
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
