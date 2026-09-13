from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = {
    "pbr_review": ROOT / "record-pbr-ab-human-review-from-plan.ps1",
    "pbr_run": ROOT / "run-pbr-ab-from-body-job.ps1",
    "throughput_start": ROOT / "start-throughput-candidate-from-ab-plan-internal.ps1",
}


def test_scoped_ab_baseline_consumers_use_bool_safe_numeric_v1_authority() -> None:
    expected = {
        "pbr_review": (
            "$plan.version",
            "$runAuthority.version",
            "$sourceAuthority.version",
            "$planAuthority.version",
            "$review.version",
        ),
        "pbr_run": (
            "$authority.version",
            "$plan.version",
            "$plan.ab_baseline_retention.version",
            "$runAuthority.version",
        ),
        "throughput_start": (
            "$plan.version",
            "$plan.ab_baseline_retention.version",
            "$candidateAuthority.version",
        ),
    }
    for name, path in SCRIPTS.items():
        source = path.read_text(encoding="utf-8")
        assert "function Test-V1Version($Value)" in source
        assert "$Value -is [bool]" in source
        assert "$Value -isnot [ValueType]" in source
        assert "[decimal]$Value -eq [decimal]1" in source
        for authority in expected[name]:
            assert f"Test-V1Version {authority}" in source
            assert f"[int]{authority}" not in source


def test_ab_baseline_consumer_authority_boundaries_remain_non_activating() -> None:
    review = SCRIPTS["pbr_review"].read_text(encoding="utf-8")
    pbr = SCRIPTS["pbr_run"].read_text(encoding="utf-8")
    throughput = SCRIPTS["throughput_start"].read_text(encoding="utf-8")

    for source in (review, pbr, throughput):
        assert "comparison_only" in source
        assert "human_visual_authority_required" in source
        assert "physical_acceptance_authority" in source
        assert "promotion_authority" in source
        assert "production_activation" in source
        assert "production_activation = $false" in source

    assert "$plan.baseline_job_id -ne $BaselineJobId" in review
    assert "$plan.baseline_job_id -ne $BaselineJobId" in pbr
    assert "$plan.baseline_job_id -ne $BaselineJobId" in throughput
    assert "$authority.contract_sha256 -ne $ContractSha256" in pbr
    assert "$candidateAuthority.contract_sha256 -ne ([string]$plan.candidate_contract_sha256).ToLowerInvariant()" in throughput


@pytest.mark.parametrize("path", tuple(SCRIPTS.values()))
def test_ab_baseline_consumer_v1_guard_runtime_semantics(path: Path) -> None:
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
