from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "prepare-photoreal-v2-p3-quest2-physical-evidence-from-machine.ps1"


def test_machine_prefill_requires_exact_openxr_machine_authority() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    for field in (
        "installed_student_hashes_verified_on_device",
        "openxr_loader_active",
        "xr_device_active",
        "xr_display_running",
        "stereo_camera_active",
        "runtime_loaded",
        "stereo_rendering_observed",
        "vr_safe_frame_pacing_observed",
        "human_runtime_visual_acceptance_required",
    ):
        assert f'"{field}"' in source
    assert 'stereo_authority -ne "unity-openxr-active-display-and-stereo-camera"' in source
    assert '@("SinglePassInstanced", "SinglePassMultiview")' in source


def test_machine_prefill_binds_exact_plan_budget_and_installed_hashes() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "p3_device_runtime_review_plan_sha256" in source
    assert "probeTargetRefresh -ne $targetRefresh" in source
    assert "probeMaxFrameTime -ne $maxFrameTime" in source
    assert "observedRefresh -lt $targetRefresh" in source
    assert "p95FrameTime -gt $maxFrameTime" in source
    assert "installed bytes differ from the runtime review plan" in source


def test_machine_prefill_never_manufactures_human_visual_acceptance() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'decision = "REVIEW_REQUIRED"' in source
    assert "operator_supplied = $false" in source
    assert 'reviewed_by = "REVIEW_REQUIRED"' in source
    assert "confirm_physical_device_review_complete = $false" in source
    assert "Until then this file is intentionally rejected" in source


def test_machine_prefill_can_only_prefill_machine_safe_evidence() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "physical_device_observed = $true" in source
    assert "stereo_rendering_observed = $true" in source
    assert "vr_safe_frame_pacing_observed = $true" in source
    assert "installed_student_hashes_verified_on_device = $true" in source
    assert "runtime_acceptance_authority =" not in source
    assert "photoreal_acceptance_authority =" not in source
    assert "production_activation" in source  # checked false on machine probe only


def test_machine_prefill_parses_when_pwsh_is_available() -> None:
    pwsh = shutil.which("pwsh")
    if pwsh is None:
        return
    command = (
        "$tokens=$null; $errors=$null; "
        f"[System.Management.Automation.Language.Parser]::ParseFile('{SCRIPT.as_posix()}', [ref]$tokens, [ref]$errors) | Out-Null; "
        "if ($errors.Count -gt 0) { $errors | ForEach-Object { Write-Error $_.Message }; exit 1 }"
    )
    subprocess.run([pwsh, "-NoProfile", "-Command", command], check=True)
