from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INTERNAL = ROOT / "start-throughput-candidate-from-ab-plan-internal.ps1"
WRAPPER = ROOT / "start-throughput-candidate-from-ab-plan.ps1"


def test_internal_retained_baseline_source_uses_bool_safe_numeric_v1() -> None:
    source = INTERNAL.read_text(encoding="utf-8")
    assert "function Test-V1Version($Value)" in source
    assert "Test-V1Version $baselineSource.version" in source
    assert "[int]$baselineSource.version" not in source
    for boundary in (
        '[string]$baselineSource.format -ne "bodyrig-pbr-ab-body-job-source"',
        '[string]$baselineSource.body_job_id -ne $BaselineJobId',
        '[string]$baselineSource.person_id -ne $personId',
        '[string]$baselineSource.bodyrig_revision -ne $mainRevision',
        '$baselineSource.safe_source_lineage_passed -ne $true',
        '$baselineSource.comparison_only -ne $true',
        '$baselineSource.human_visual_authority_required -ne $true',
        '$baselineSource.physical_acceptance_authority -ne $false',
        '$baselineSource.production_activation -ne $false',
    ):
        assert boundary in source


def test_wrapper_run_plan_result_uses_bool_safe_numeric_v1() -> None:
    source = WRAPPER.read_text(encoding="utf-8")
    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source
    assert "Test-V1Version $candidateResult.version" in source
    assert "[int]$candidateResult.version" not in source
    for boundary in (
        '[string]$candidateResult.format -eq "bodyrig-throughput-candidate-run-plan"',
        '$machineResults.Count -ne 1',
        '[string]$started.person_id -ne [string]$gateBefore.person_id',
        'Try-CancelCandidateJob -JobId $candidateJobId -UriBase $BaseUri',
        'candidate_run_plan_sha256 = $runPlanSha',
        'comparison_only = $true',
        'physical_acceptance_authority = $false',
        'promotion_authority = $false',
        'production_activation = $false',
    ):
        assert boundary in source


@pytest.mark.parametrize("path", (INTERNAL, WRAPPER))
def test_throughput_start_v1_guard_runtime_semantics(path: Path) -> None:
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
