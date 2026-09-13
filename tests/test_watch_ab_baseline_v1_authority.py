from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "watch-body-build.ps1"


def test_watch_ab_baseline_uses_bool_safe_numeric_v1_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source
    assert "Test-V1Version $plan.version" in source
    assert "Test-V1Version $retention.version" in source
    assert "[int]$plan.version" not in source
    assert "[int]$retention.version" not in source


def test_watch_ab_baseline_preserves_exact_job_and_non_activation_bindings() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for boundary in (
        '[string]$plan.baseline_job_id -eq $jobId',
        '[string]$plan.person_id -eq [string]$Job.person_id',
        '[string]$plan.baseline_bodyrig_revision -eq [string]$Job.bodyrig_revision',
        '[string]$plan.candidate_contract_sha256 -match \'^[0-9a-f]{64}$\'',
        '$plan.pbr_candidate.retained_reconstruction_reuse -eq $true',
        '$plan.throughput_candidate.separate_candidate_body_build_required -eq $true',
        '$retention.retain_private_workspace -eq $true',
        '[string]$retention.job_id -eq $jobId',
        '[string]$retention.expected_bodyrig_revision -eq [string]$Job.bodyrig_revision',
        '$plan.comparison_only -eq $true',
        '$plan.human_visual_authority_required -eq $true',
        '$plan.physical_acceptance_authority -eq $false',
        '$plan.promotion_authority -eq $false',
        '$plan.production_activation -eq $false',
    ):
        assert boundary in source


def test_watch_ab_baseline_continuation_rejects_non_numeric_v1_runtime() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    path = str(SCRIPT.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors)
if ($errors.Count -ne 0) {{ exit 20 }}
foreach ($name in @('Read-JsonFile', 'Test-V1Version', 'Get-AbBaselineContinuation')) {{
    $fn = $ast.Find({{ param($node) $node -is [System.Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $name }}, $true)
    if ($null -eq $fn) {{ exit 21 }}
    Invoke-Expression $fn.Extent.Text
}}

$oldLocalAppData = [string]$env:LOCALAPPDATA
$root = Join-Path ([System.IO.Path]::GetTempPath()) ('bodyrig-watch-ab-v1-' + [Guid]::NewGuid().ToString('N'))
$env:LOCALAPPDATA = $root
$jobId = 'job-' + ('1' * 32)
$personId = 'person-' + ('2' * 32)
$revision = '3' * 40
$planDir = Join-Path $root 'BodyRig\ab-baseline-plans'
$planPath = Join-Path $planDir ($jobId + '.json')
New-Item -ItemType Directory -Path $planDir -Force | Out-Null
$job = [pscustomobject]@{{ job_id = $jobId; person_id = $personId; bodyrig_revision = $revision }}

function Test-Plan([object]$PlanVersion, [object]$RetentionVersion, [string]$ExpectedState) {{
    $plan = [ordered]@{{
        format = 'bodyrig-dual-candidate-ab-baseline-plan'
        version = $PlanVersion
        baseline_job_id = $jobId
        person_id = $personId
        baseline_bodyrig_revision = $revision
        candidate_contract_sha256 = 'a' * 64
        pbr_candidate = [ordered]@{{ revision = '4' * 40; retained_reconstruction_reuse = $true }}
        throughput_candidate = [ordered]@{{ revision = '5' * 40; separate_candidate_body_build_required = $true }}
        ab_baseline_retention = [ordered]@{{
            format = 'bodyrig-ab-baseline-retention'
            version = $RetentionVersion
            retain_private_workspace = $true
            job_id = $jobId
            expected_bodyrig_revision = $revision
        }}
        comparison_only = $true
        human_visual_authority_required = $true
        physical_acceptance_authority = $false
        promotion_authority = $false
        production_activation = $false
    }}
    $plan | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $planPath -Encoding utf8
    $result = Get-AbBaselineContinuation -Job $job
    if ([string]$result.State -ne $ExpectedState) {{
        throw "Expected $ExpectedState for plan=$PlanVersion retention=$RetentionVersion, got $($result.State)"
    }}
}}

try {{
    Test-Plan 1 1 'valid'
    Test-Plan 1.0 1.0 'valid'
    Test-Plan $true 1 'invalid'
    Test-Plan '1' 1 'invalid'
    Test-Plan $null 1 'invalid'
    Test-Plan 1 $true 'invalid'
    Test-Plan 1 '1' 'invalid'
    Test-Plan 1 $null 'invalid'
}}
finally {{
    if ([string]::IsNullOrEmpty($oldLocalAppData)) {{ Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue }} else {{ $env:LOCALAPPDATA = $oldLocalAppData }}
    Remove-Item -LiteralPath $root -Recurse -Force -ErrorAction SilentlyContinue
}}
exit 0
"""
    result = subprocess.run(
        [pwsh, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
