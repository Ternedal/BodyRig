from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "continue-throughput-review-from-ab-plan.ps1"


def test_continuation_uses_bool_safe_numeric_v1_at_all_scoped_authorities() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source

    expected = (
        "$value.version",
        "$gateReceipt.version",
        "$live.version",
        "$sharedPlan.version",
        "$runPlan.version",
        "$baselineJob.version",
        "$retention.version",
        "$candidateJob.version",
        "$machine.version",
        "$bundle.version",
    )
    for authority in expected:
        assert f"Test-V1Version {authority}" in source
        assert f"[int]{authority}" not in source


def test_continuation_preserves_plan_source_and_non_activation_boundaries() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for boundary in (
        '[string]$gateReceipt.baseline_job_id -ne $BaselineJobId',
        '[string]$gateReceipt.candidate_job_id -ne $CandidateJobId',
        '[string]$gateReceipt.person_id -ne $ExpectedPersonId',
        '[string]$live.stash_performer_id -ne $stashPerformerId',
        '[string]$runPlan.baseline_job_id -ne $BaselineJobId',
        '[string]$runPlan.candidate_job_id -ne $CandidateJobId',
        '[string]$baselineJob.job_id -ne $BaselineJobId',
        '[string]$candidateJob.job_id -ne $CandidateJobId',
        '[string]$retention.job_id -ne $BaselineJobId',
        '[string]$baselineReceipts.source_evidence_sha256 -ne [string]$candidateReceipts.source_evidence_sha256',
        '[string]$baselineReceipts.source_files_sha256 -ne [string]$candidateReceipts.source_files_sha256',
        '$originMainAfter -ne $mainRevision -or $originCandidateAfter -ne $throughputRevision',
        'Write-CreateOnlyJson -Path $authorityPath -Value $authority',
        'comparison_only = $true',
        'human_visual_authority_required = $true',
        'physical_acceptance_authority = $false',
        'promotion_authority = $false',
        'production_activation = $false',
        'Authority: comparison-only; human decision still required; no physical acceptance, promotion or production activation.',
    ):
        assert boundary in source


def test_continuation_v1_guard_runtime_semantics() -> None:
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
