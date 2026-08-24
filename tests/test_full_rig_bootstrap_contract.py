from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_full_rig_bootstrap_runs_both_provisioners_and_validates_master_report():
    text = (ROOT / "setup-rig-windows.ps1").read_text(encoding="utf-8")
    assert "setup-recovery-windows.ps1" in text
    assert "setup-high-fidelity-wsl.ps1" in text
    assert 'format = "bodyrig-rig-setup"' in text
    assert '"-m", "bodyrig.rig_setup"' not in text  # invocation uses native PowerShell argument form
    assert "-m bodyrig.rig_setup $temp" in text
    assert "environment_summary_sha256 = Get-Sha256" in text
    assert "preflight_sha256 = Get-Sha256" in text
    assert "setup_report_sha256 = Get-Sha256" in text
    assert "BODYRIG_RIG_SETUP_REPORT" in text


def test_full_rig_bootstrap_rehydrates_sith_environment_in_parent_process():
    text = (ROOT / "setup-rig-windows.ps1").read_text(encoding="utf-8")
    assert "Set-BodyRigEnvironment" in text
    assert "BODYRIG_SITH_SETUP_REPORT = $SithSetupReport" in text
    assert "BODYRIG_SITH_DISTRIBUTION = [string]$sithSetup.distribution" in text
    assert "BODYRIG_SITH_REPO = [string]$sithSetup.sith.repository" in text
    assert "BODYRIG_SITH_PYTHON = [string]$sithSetup.sith.python" in text
    assert "BODYRIG_SITH_OPENPOSE_REPO = [string]$sithSetup.openpose.repository" in text
    assert "BODYRIG_SITH_OPENPOSE = [string]$sithSetup.openpose.executable" in text
    assert "BODYRIG_SITH_OPENPOSE_SHA256 = ([string]$sithSetup.openpose.sha256).ToLowerInvariant()" in text
    assert "BODYRIG_SITH_OPENPOSE_MODELS_SHA256 = ([string]$sithSetup.openpose.models_sha256).ToLowerInvariant()" in text
    assert "BODYRIG_SITH_DIFFUSION_MODEL = [string]$sithSetup.diffusion_model.path" in text
    assert "BODYRIG_SITH_DIFFUSION_SHA256 = ([string]$sithSetup.diffusion_model.sha256).ToLowerInvariant()" in text
    assert "Set-BodyRigEnvironment -Values $sithEnvironment -Persist:$PersistUserEnvironment" in text


def test_full_rig_bootstrap_points_operator_to_live_ready_launcher():
    text = (ROOT / "setup-rig-windows.ps1").read_text(encoding="utf-8")
    assert "Next physical clone (runs live readiness before clone):" in text
    assert '.\\clone-body-from-stash-ready.ps1 -PerformerId <id> -BodyId <id>' in text
    assert 'Write-Host ".\\clone-body-from-stash.ps1 ' not in text


def test_full_rig_bootstrap_keeps_licensed_assets_explicit():
    text = (ROOT / "setup-rig-windows.ps1").read_text(encoding="utf-8")
    assert '[string]$SmplModelPath = ""' in text
    assert '[string]$SmplxSource = ""' in text
    assert '"-SmplModelPath", $SmplModelPath' in text
    assert '"-SmplxSource", $SmplxSource' in text
