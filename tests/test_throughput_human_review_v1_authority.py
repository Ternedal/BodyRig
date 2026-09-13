from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "record-throughput-human-review-from-ab-plan-internal.ps1"


def test_human_review_uses_bool_safe_numeric_v1_at_all_scoped_authorities() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    assert "function Test-V1Version($Value)" in source
    assert "$Value -is [bool]" in source
    assert "$Value -isnot [ValueType]" in source
    assert "[decimal]$Value -eq [decimal]1" in source

    expected = (
        "$value.version",
        "$continuation.version",
        "$sharedPlan.version",
        "$runPlan.version",
    )
    for authority in expected:
        assert f"Test-V1Version {authority}" in source
        assert f"[int]{authority}" not in source


def test_human_review_preserves_explicit_review_and_fail_closed_boundaries() -> None:
    source = SCRIPT.read_text(encoding="utf-8")

    for boundary in (
        'if (-not $ConfirmVisualReview)',
        'Note must contain the operator\'s actual visual A/B assessment.',
        '[string]$continuation.baseline_job_id -ne $BaselineJobId',
        '[string]$continuation.candidate_job_id -ne $CandidateJobId',
        '[string]$sharedPlan.person_id -ne $personId',
        '[string]$runPlan.baseline_job_id -ne $BaselineJobId',
        '[string]$runPlan.candidate_job_id -ne $CandidateJobId',
        'Assert-CheckoutAndRefs -CandidateRef $throughputRef -MainRevision $mainRevision -CandidateRevision $throughputRevision',
        '[string]$baselineProbe.source_evidence_sha256 -ne $sourceManifestSha',
        '[string]$candidateProbe.source_files_sha256 -ne $sourceFilesSha',
        'Write-CreateOnlyJson -Path $humanAuthorityPath -Value $authority',
        'human_visual_authority_recorded = $true',
        'physical_acceptance_authority = $false',
        'promotion_authority = $false',
        'production_activation = $false',
        'Remove-Item -LiteralPath $humanReviewPath -Force -ErrorAction SilentlyContinue',
        'Remove-Item -LiteralPath $humanAuthorityPath -Force -ErrorAction SilentlyContinue',
        'Authority: comparison-only human evidence; no physical acceptance, promotion or production activation.',
    ):
        assert boundary in source

    assert 'human_visual_review_passed = [bool]$review.human_visual_review_passed' in source
    assert 'decision = [string]$review.decision' in source


def test_human_review_v1_guard_runtime_semantics() -> None:
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
