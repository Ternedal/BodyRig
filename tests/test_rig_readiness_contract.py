from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readiness_gate_checks_live_dependencies_without_starting_clone():
    text = (ROOT / "check-rig-ready.ps1").read_text(encoding="utf-8")
    assert "bodyrig.rig_setup" in text
    assert "bodyrig.preflight_cli" in text
    assert "bodyrig.sith_preflight" in text
    assert "bodyrig.wsl_file_digest" in text
    assert "bodyrig.sith_model" in text
    assert '"bodyrig.stash_cli", "health"' in text
    assert "bodyrig.recover_cli" not in text
    assert "bodyrig.observation_cli" not in text
    assert "bodyrig.identity_capture_cli" not in text
    assert "bodyrig.external_fitter_cli" not in text


def test_readiness_gate_rechecks_binary_and_model_bytes_and_emits_all_green_evidence():
    text = (ROOT / "check-rig-ready.ps1").read_text(encoding="utf-8")
    assert "Live OpenPose binary SHA-256 mismatch" in text
    assert "Live OpenPose binary byte count differs from setup evidence" in text
    assert "Live diffusion model SHA-256 mismatch" in text
    assert "Live diffusion model tree counts differ from setup evidence" in text
    assert 'format = "bodyrig-rig-readiness"' in text
    assert "master_setup = $true" in text
    assert "recovery = $true" in text
    assert "sith_openpose = $true" in text
    assert "openpose_binary = $true" in text
    assert "diffusion_model = $true" in text
    assert "stash = $true" in text
    assert "openpose_sha256 = $actualOpenPoseHash" in text
    assert "ready = $true" in text
