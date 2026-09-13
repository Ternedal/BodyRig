from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "run-pbr-ab-from-body-job.ps1"


def test_pbr_ab_runner_uses_bool_safe_numeric_v1_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source

    for authority in (
        "$authority.version",
        "$plan.version",
        "$plan.ab_baseline_retention.version",
        "$runAuthority.version",
    ):
        assert f"Test-V1Version {authority}" in source
        assert f"[int]{authority}" not in source


def test_pbr_ab_runner_preserves_plan_candidate_run_and_non_activation_bindings() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for boundary in (
        '[string]$authority.main_revision -ne $MainRevision',
        '[string]$authority.contract_sha256 -ne $ContractSha256',
        '[string]$authority.candidates.pbr_v3.revision -ne $PbrRevision',
        '[string]$authority.candidates.recovery_throughput_v3.revision -ne $ThroughputRevision',
        '$authority.comparison_only -ne $true',
        '$authority.human_visual_authority_required -ne $true',
        '$authority.physical_acceptance_authority -ne $false',
        '$authority.promotion_authority -ne $false',
        '$authority.production_activation -ne $false',
        '[string]$plan.baseline_job_id -ne $BaselineJobId',
        '[string]$plan.person_id -notmatch \'^person-[0-9a-f]{32}$\'',
        '[string]$plan.candidate_contract_sha256 -notmatch \'^[0-9a-f]{64}$\'',
        '$plan.comparison_only -ne $true',
        '$plan.human_visual_authority_required -ne $true',
        '$plan.physical_acceptance_authority -ne $false',
        '$plan.promotion_authority -ne $false',
        '$plan.production_activation -ne $false',
        '$plan.ab_baseline_retention.retain_private_workspace -ne $true',
        '[string]$plan.ab_baseline_retention.job_id -ne $BaselineJobId',
        '([string]$plan.ab_baseline_retention.expected_bodyrig_revision).ToLowerInvariant() -ne $mainRevision',
        '([string]$runAuthority.baseline_revision).ToLowerInvariant() -ne $mainRevision',
        '([string]$runAuthority.candidate_revision).ToLowerInvariant() -ne $pbrRevision',
        '$runAuthority.comparison_only -ne $true',
        '$runAuthority.physical_acceptance_authority -ne $false',
        '$runAuthority.production_activation -ne $false',
        'run_authority_sha256 = (Get-FileHash -LiteralPath $runAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()',
        'source_authority_sha256 = (Get-FileHash -LiteralPath $sourceAuthorityPath -Algorithm SHA256).Hash.ToLowerInvariant()',
        'comparison_only = $true',
        'human_visual_authority_required = $true',
        'physical_acceptance_authority = $false',
        'promotion_authority = $false',
        'production_activation = $false',
    ):
        assert boundary in source


def test_pbr_ab_runner_v1_guard_runtime_semantics() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    path = str(SCRIPT.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{path}', [ref]$tokens, [ref]$errors)
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
