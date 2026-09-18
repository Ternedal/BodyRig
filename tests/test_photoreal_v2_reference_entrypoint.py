from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "start-photoreal-v2-reference.ps1").read_text(encoding="utf-8")


def test_entrypoint_requires_explicit_insightface_license_acceptance_for_first_setup() -> None:
    assert "[switch]$AcceptInsightFaceResearchLicense" in SCRIPT
    assert "First-time/reference-model repair requires explicit -AcceptInsightFaceResearchLicense" in SCRIPT
    assert "AcceptInsightFaceResearchLicense = $true" in SCRIPT
    acceptance_check = SCRIPT.index("if (-not $AcceptInsightFaceResearchLicense)")
    model_setup = SCRIPT.index("& $modelSetup @modelArgs")
    assert acceptance_check < model_setup


def test_entrypoint_uses_default_persistent_model_root_but_not_repo_storage() -> None:
    assert 'Join-Path $env:LOCALAPPDATA "BodyRig\\photoreal-v2\\reference-models"' in SCRIPT
    assert "ModelRoot = [IO.Path]::GetFullPath($ModelRoot)" in SCRIPT
    assert "reference-models" in SCRIPT
    assert "git -C $repoRoot status --porcelain" in SCRIPT


def test_entrypoint_requires_complete_models_and_runtime_before_p0() -> None:
    model_manifest = SCRIPT.index('bodyrig-reference-vision-v1.json')
    runtime_receipt = SCRIPT.index('runtime-environment.json')
    run = SCRIPT.index("& $runner @runArgs")
    assert model_manifest < runtime_receipt < run
    assert "Photoreal reference model setup returned without a complete model root." in SCRIPT
    assert "Photoreal reference WSL setup returned without a runtime environment receipt." in SCRIPT


def test_entrypoint_repairs_only_with_explicit_switches() -> None:
    assert "[switch]$RepairReferenceModels" in SCRIPT
    assert "[switch]$RepairReferenceEnvironment" in SCRIPT
    assert "Re-run with -RepairReferenceModels" in SCRIPT
    assert "Re-run with -RepairReferenceEnvironment" in SCRIPT
    assert "if ($RepairReferenceEnvironment) { $wslArgs.Force = $true }" in SCRIPT


def test_entrypoint_preserves_authority_boundaries() -> None:
    assert 'Write-Host "Reconstruction:    FALSE"' in SCRIPT
    assert 'Write-Host "Photoreal accept:  FALSE"' in SCRIPT
    assert 'Write-Host "Production:        FALSE"' in SCRIPT
    assert "bodyrig.sith_" not in SCRIPT
    assert "reference-renderer" not in SCRIPT
    assert "Vrm" not in SCRIPT


def test_entrypoint_runs_reference_p0_only_after_setup_checks() -> None:
    model_setup = SCRIPT.index("& $modelSetup @modelArgs")
    wsl_setup = SCRIPT.index("& $wslSetup @wslArgs")
    p0 = SCRIPT.index("& $runner @runArgs")
    assert model_setup < p0
    assert wsl_setup < p0
