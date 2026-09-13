from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build-source-hair-eye-review-runtime.ps1"
PREVIEW = ROOT / "run-source-hair-eye-windows-preview.ps1"


def test_source_hair_eye_runtime_and_preview_use_bool_safe_numeric_v1() -> None:
    build = BUILD.read_text(encoding="utf-8")
    preview = PREVIEW.read_text(encoding="utf-8")

    for source in (build, preview):
        assert "function Test-V1Version($Value)" in source
        assert "$Value -is [bool]" in source
        assert "$Value -isnot [ValueType]" in source
        assert "[decimal]$Value -eq [decimal]1" in source

    assert "Test-V1Version $receipt.version" in build
    assert "[int]$receipt.version" not in build

    for reader in ("$sourceReview.version", "$authority.version", "$hairProbe.version"):
        assert f"Test-V1Version {reader}" in preview
        assert f"[int]{reader}" not in preview


def test_runtime_builder_preserves_review_only_authority_boundary() -> None:
    source = BUILD.read_text(encoding="utf-8")

    for boundary in (
        'bodyrig-source-hair-eye-review-runtime',
        '[string]$receipt.bodyrigRevision -ne $head',
        '[string]$receipt.bridgeScriptSha256 -ne $bridgeScriptSha',
        '[string]$receipt.reviewVrmSha256 -ne (Sha256 $reviewVrmPath)',
        '[string]$receipt.runtimeIntegrationStatus -ne "hair-and-eyes-review-artifact-ready"',
        '$receipt.sourceHairRuntimeApplied -ne $true',
        '$receipt.sourceEyeSurfaceApplied -ne $true',
        '[string]$receipt.cornealMaterialStatus -ne "runtime-applied"',
        '$receipt.physicalSilhouetteReviewRequired -ne $true',
        '$receipt.physicalFaceCloseupReviewRequired -ne $true',
        '$receipt.comparisonOnly -ne $true',
        '$receipt.humanReviewRequired -ne $true',
        '$receipt.hairComponentAuthority -ne $false',
        '$receipt.eyeComponentAuthority -ne $false',
        '$receipt.productionActivation -ne $false',
        'Assert-CheckoutAuthority -RepoRoot $repoRoot -ExpectedHead $head',
        '(Sha256 $bridgeScript) -ne $bridgeScriptSha',
    ):
        assert boundary in source


def test_windows_preview_preserves_hashes_deformation_and_nonactivation() -> None:
    source = PREVIEW.read_text(encoding="utf-8")

    for boundary in (
        'bodyrig-source-hair-eye-review-runtime',
        '[string]$sourceReview.bodyrigRevision -ne $head',
        '[string]$sourceReview.reviewVrmSha256 -ne (Sha256 $sourceReviewVrm)',
        '$sourceReview.comparisonOnly -ne $true',
        '$sourceReview.humanReviewRequired -ne $true',
        '$sourceReview.productionActivation -ne $false',
        'bodyrig-source-hair-eye-preview-runtime',
        '[string]$authority.bodyrigRevision -ne $head',
        '[string]$authority.reviewVrmSha256 -ne (Sha256 $previewAvatar)',
        '[string]$authority.runtimeManifestSha256 -ne (Sha256 $runtimeManifest)',
        '$authority.physicalAcceptanceAuthority -ne $false',
        '$authority.productionActivation -ne $false',
        '(Need-Sha256 ([string]$comparison.hair_deformation_probe_sha256) "comparison hair deformation SHA") -ne $hairProbeSha',
        '$comparison.hair_deformation_machine_pass -ne $true',
        '$comparison.hair_deformation_human_review_required -ne $true',
        '$comparison.physical_acceptance_authority -ne $false',
        '$comparison.production_activation -ne $false',
        'bodyrig-hair-deformation-probe',
        '[string]$hairProbe.bodyrig_revision -ne $head',
        '[string]$hairProbe.package_sha256 -ne [string]$sourceReview.packageSha256',
        '[string]$hairProbe.avatar_sha256 -ne (Sha256 $sourceReviewVrm)',
        '[string]$hairProbe.sequence_revision -ne "source-hair-head-turn-v1"',
        '$hairProbe.human_review_required -ne $true',
        '$hairProbe.comparison_only -ne $true',
        '$hairProbe.hair_component_authority -ne $false',
        '$hairProbe.production_activation -ne $false',
        '[double]$hairProbe.observed_head_turn_degrees -lt 18.2',
        '[double]$hairProbe.vertex_motion_rms_m -lt 0.00025',
        '[double]$hairProbe.vertex_motion_max_m -lt 0.001',
        '[double]$hairProbe.restoration_rms_m -gt 0.00025',
        '[double]$hairProbe.restoration_max_m -gt 0.001',
        'Assert-CleanHead -RepoRoot $repoRoot -Expected $head',
    ):
        assert boundary in source


@pytest.mark.parametrize("script_path", [BUILD, PREVIEW])
def test_source_hair_eye_v1_guard_runtime_semantics(script_path: Path) -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("PowerShell 7 is unavailable")

    escaped = str(script_path.resolve()).replace("'", "''")
    script = rf"""
$tokens = $null
$errors = $null
$ast = [System.Management.Automation.Language.Parser]::ParseFile('{escaped}', [ref]$tokens, [ref]$errors)
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
