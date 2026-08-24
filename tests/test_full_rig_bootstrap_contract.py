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


def test_full_rig_bootstrap_keeps_licensed_assets_explicit():
    text = (ROOT / "setup-rig-windows.ps1").read_text(encoding="utf-8")
    assert '[string]$SmplModelPath = ""' in text
    assert '[string]$SmplxSource = ""' in text
    assert '"-SmplModelPath", $SmplModelPath' in text
    assert '"-SmplxSource", $SmplxSource' in text
