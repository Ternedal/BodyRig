from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "check-photoreal-v2-exavatar-readiness.ps1").read_text(encoding="utf-8")


def test_exavatar_readiness_doctor_is_read_only() -> None:
    assert "mutates_environment = $false" in SCRIPT
    assert "downloads_assets = $false" in SCRIPT
    assert "setup-photoreal-exavatar-public-code.ps1" not in SCRIPT
    assert "setup-photoreal-exavatar-wsl.ps1" not in SCRIPT
    assert "apt-get" not in SCRIPT
    assert "git clone" not in SCRIPT
    assert "Invoke-WebRequest" not in SCRIPT
    assert "Start-BitsTransfer" not in SCRIPT


def test_exavatar_readiness_doctor_checks_gpu_cuda_and_receipts() -> None:
    assert "nvidia-smi" in SCRIPT
    assert '"nvcc","--version"' in SCRIPT
    assert 'nvcc must report CUDA 12.4' in SCRIPT
    assert "bodyrig-public-dependencies.json" in SCRIPT
    assert "bodyrig-exavatar-runtime-setup.json" in SCRIPT
    assert "LinuxMaterializerPython" in SCRIPT


def test_exavatar_readiness_doctor_reuses_strict_asset_preflight() -> None:
    assert "bodyrig.photoreal_exavatar_preflight_cli" in SCRIPT
    assert "--dependency-root" in SCRIPT
    assert "--asset-root" in SCRIPT
    assert "--reference-model-root" in SCRIPT
    assert "--smplx-gender" in SCRIPT
    assert "--no-colmap" in SCRIPT
    assert "missing_restricted_assets" in SCRIPT
    assert "missing_nonrestricted_assets" in SCRIPT
    assert "public_repository_issues" in SCRIPT


def test_exavatar_readiness_doctor_keeps_authority_false() -> None:
    assert "exavatar_launch_prerequisites_ready = [bool]$ready" in SCRIPT
    assert "photoreal_acceptance_authority = $false" in SCRIPT
    assert "human_visual_acceptance_required = $true" in SCRIPT
    assert "production_activation = $false" in SCRIPT


def test_exavatar_readiness_doctor_defaults_match_teacher_operator() -> None:
    assert 'LinuxDependencyRoot = "/opt/bodyrig-exavatar/deps"' in SCRIPT
    assert 'LinuxRuntimePython = "/opt/bodyrig-exavatar/bin/python"' in SCRIPT
    assert 'LinuxMaterializerPython = "/opt/bodyrig-photoreal/bin/python"' in SCRIPT
    assert 'Distribution = "Ubuntu-22.04"' in SCRIPT
    assert 'Join-Path $env:LOCALAPPDATA "BodyRig\\photoreal-v2\\reference-models"' in SCRIPT
