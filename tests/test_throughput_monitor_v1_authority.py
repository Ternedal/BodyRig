from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "watch-throughput-candidate-from-ab-plan.ps1"


def test_monitor_uses_bool_safe_numeric_v1_at_all_scoped_authorities() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source

    expected = (
        "$job.version",
        "$runPlan.version",
        "$sourceAuthority.version",
        "$gate.version",
    )
    for authority in expected:
        assert f"Test-V1Version {authority}" in source
        assert f"[int]{authority}" not in source


def test_monitor_preserves_exact_routing_and_non_activation_boundaries() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for boundary in (
        '[string]$job.job_id -ne $CandidateJobId',
        '[string]$runPlan.baseline_job_id -ne $BaselineJobId',
        '[string]$runPlan.candidate_job_id -ne $CandidateJobId',
        '[string]$runPlan.person_id -ne [string]$job.person_id',
        '[string]$sourceAuthority.job_id -ne $CandidateJobId',
        '[string]$sourceAuthority.person_id -ne [string]$runPlan.person_id',
        '[string]$gate.baseline_job_id -ne $BaselineJobId',
        '[string]$gate.candidate_job_id -ne $CandidateJobId',
        '[string]$gate.person_id -ne [string]$runPlan.person_id',
        '[string]$gate.stash_performer_id -ne [string]$sourceAuthority.stash_performer_id',
        '([string]$gate.candidate_run_plan_sha256).ToLowerInvariant() -ne $runPlanSha',
        '$runPlan.comparison_only -ne $true',
        '$runPlan.human_visual_authority_required -ne $true',
        '$runPlan.physical_acceptance_authority -ne $false',
        '$runPlan.promotion_authority -ne $false',
        '$runPlan.production_activation -ne $false',
        '$gate.human_visual_authority_recorded -ne $true',
        '$gate.physical_acceptance_authority -ne $false',
        '$gate.promotion_authority -ne $false',
        '$gate.production_activation -ne $false',
        'Authority: advisory routing only; no physical acceptance, promotion or production activation.',
    ):
        assert boundary in source

    assert 'if ($status -ne "succeeded")' in source
    assert 'continue-throughput-review-from-ab-plan.ps1' in source


def test_monitor_v1_guard_runtime_semantics() -> None:
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
