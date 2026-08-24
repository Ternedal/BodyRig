from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_readiness_gate_checks_live_dependencies_without_starting_clone():
    text = (ROOT / "check-rig-ready.ps1").read_text(encoding="utf-8")
    assert "bodyrig.rig_setup" in text
    assert "bodyrig.preflight_cli" in text
    assert "bodyrig.sith_preflight" in text
    assert "bodyrig.wsl_file_digest" in text
    assert "bodyrig.wsl_tree_digest" in text
    assert "bodyrig.sith_model" in text
    assert '"bodyrig.stash_cli", "health"' in text
    assert "bodyrig.recover_cli" not in text
    assert "bodyrig.observation_cli" not in text
    assert "bodyrig.identity_capture_cli" not in text
    assert "bodyrig.external_fitter_cli" not in text


def test_readiness_gate_rechecks_openpose_diffusion_and_stash_capability_and_emits_all_green_evidence():
    text = (ROOT / "check-rig-ready.ps1").read_text(encoding="utf-8")
    assert "Live OpenPose binary SHA-256 mismatch" in text
    assert "Live OpenPose binary byte count differs from setup evidence" in text
    assert "Live OpenPose model tree SHA-256 mismatch" in text
    assert "Live OpenPose model tree counts differ from setup evidence" in text
    assert "Live diffusion model SHA-256 mismatch" in text
    assert "Live diffusion model tree counts differ from setup evidence" in text
    assert "Stash health probe did not prove performer-read capability" in text
    assert 'format = "bodyrig-rig-readiness"' in text
    assert "master_setup = $true" in text
    assert "recovery = $true" in text
    assert "sith_openpose = $true" in text
    assert "openpose_binary = $true" in text
    assert "openpose_models = $true" in text
    assert "diffusion_model = $true" in text
    assert "stash = $true" in text
    assert "stash_performer_read = $true" in text
    assert "openpose_sha256 = $actualOpenPoseHash" in text
    assert "openpose_models_sha256 = $actualOpenPoseModelsHash" in text
    assert "ready = $true" in text


def test_readiness_schema_matches_the_fields_emitted_by_live_readiness():
    schema = json.loads((ROOT / "contracts" / "rig-readiness-v1.schema.json").read_text(encoding="utf-8"))

    check_fields = {
        "master_setup",
        "recovery",
        "sith_openpose",
        "openpose_binary",
        "openpose_models",
        "diffusion_model",
        "stash",
        "stash_performer_read",
    }
    assert set(schema["properties"]["checks"]["required"]) == check_fields
    assert set(schema["properties"]["checks"]["properties"]) == check_fields

    environment_fields = {
        "stash_version",
        "openpose_sha256",
        "openpose_byte_count",
        "openpose_models_sha256",
        "openpose_models_file_count",
        "openpose_models_byte_count",
        "diffusion_model_sha256",
        "diffusion_model_file_count",
        "diffusion_model_byte_count",
    }
    assert set(schema["properties"]["environment"]["required"]) == environment_fields
    assert set(schema["properties"]["environment"]["properties"]) == environment_fields
