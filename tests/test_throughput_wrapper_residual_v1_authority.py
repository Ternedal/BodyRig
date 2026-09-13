from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "start-throughput-candidate-from-ab-plan.ps1"


def test_throughput_wrapper_residual_v1_authorities_are_bool_safe() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert source.count("Test-V1Version $value.version") == 2
    assert "Test-V1Version $humanAuthority.version" in source
    assert "Test-V1Version $sourceAuthority.version" in source
    # The same sourceAuthority variable is also the live enqueue authority later in the wrapper.
    assert source.count("Test-V1Version $sourceAuthority.version") == 2

    for coercive in (
        "[int]$value.version",
        "[int]$humanAuthority.version",
        "[int]$sourceAuthority.version",
    ):
        assert coercive not in source


def test_throughput_wrapper_residual_bindings_remain_fail_closed() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for boundary in (
        'bodyrig-pbr-human-review-gate-context',
        'bodyrig-succeeded-body-job-receipt-authority',
        'bodyrig-pbr-plan-bound-human-review-authority',
        'bodyrig-pbr-ab-body-job-source-authority',
        'bodyrig-body-build-source-enqueue-authority',
        '[string]$value.stash_performer_id -ne [string]$Gate.stash_performer_id',
        '$humanAuthorityShaBefore -ne [string]$Gate.pbr_human_review_authority_sha256',
        '$sourceAuthorityShaBefore -ne $reviewedSourceSha',
        '[string]$sourceAuthority.stash_performer_id -ne [string]$gateBefore.stash_performer_id',
        'Try-CancelCandidateJob -JobId $candidateJobId -UriBase $BaseUri',
        '$value.comparison_only -ne $true',
        '$value.physical_acceptance_authority -ne $false',
        '$value.promotion_authority -ne $false',
        '$value.production_activation -ne $false',
        '$sourceAuthority.physical_acceptance_authority -ne $false',
        '$sourceAuthority.production_activation -ne $false',
        'production_activation = $false',
    ):
        assert boundary in source


def test_throughput_wrapper_v1_guard_runtime_semantics() -> None:
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
