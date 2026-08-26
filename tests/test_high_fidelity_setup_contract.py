from __future__ import annotations

from pathlib import Path

from bodyrig.sith_preflight import OPENPOSE_REVISION, SITH_REVISION


ROOT = Path(__file__).resolve().parents[1]


def test_openpose_setup_pins_revision_and_cuda_build():
    text = (ROOT / "setup-openpose-wsl.ps1").read_text(encoding="utf-8")
    assert OPENPOSE_REVISION in text
    assert '"-DGPU_MODE=CUDA"' in text
    # BodyRig owns model download + digest verification explicitly. CMake must
    # not perform an independent, unbound model download during configuration.
    assert '"-DDOWNLOAD_BODY_25_MODEL=OFF"' in text
    assert '"-DDOWNLOAD_FACE_MODEL=OFF"' in text
    assert '"-DDOWNLOAD_HAND_MODEL=OFF"' in text
    assert "Get-WslMd5" in text
    assert 'RelativePath = "pose/body_25/pose_iter_584000.caffemodel"' in text
    assert 'Md5 = "78287b57cf85fa89c03f1393d368e5b7"' in text
    assert 'RelativePath = "face/pose_iter_116000.caffemodel"' in text
    assert 'Md5 = "e747180d728fa4e4418c465828384333"' in text
    assert 'RelativePath = "hand/pose_iter_102000.caffemodel"' in text
    assert 'Md5 = "a82cfc3fea7c62f159e11bd3674c1531"' in text
    assert 'build/examples/openpose/openpose.bin' in text
    assert 'hash-object", "CMakeLists.txt"' in text
    assert "sudo" not in text.lower()


def test_top_level_setup_binds_sith_checkpoints_openpose_binary_models_and_diffusion_report():
    text = (ROOT / "setup-high-fidelity-wsl.ps1").read_text(encoding="utf-8")
    assert SITH_REVISION in text
    assert OPENPOSE_REVISION in text
    assert "setup-openpose-wsl.ps1" in text
    assert "setup-sith-wsl.ps1" in text
    assert '"--openpose-repo", $OpenPoseRepo' in text
    assert "bodyrig.wsl_file_digest" in text
    assert "bodyrig.wsl_tree_digest" in text
    assert '$OpenPoseModels = "$OpenPoseRepo/models"' in text
    assert '$reconCheckpoint = "$SithInstallRoot/checkpoints/recon_model.pth"' in text
    assert '$smplerxCheckpoint = "$SithInstallRoot/checkpoints/save_smplerx.pth"' in text
    assert '"-m", "bodyrig.sith_model"' in text
    assert 'format = "bodyrig-sith-setup"' in text
    assert "version = 4" in text
    assert "checkpoints = [ordered]@{" in text
    assert "sha256 = ([string]$reconCheckpointDigest.sha256).ToLowerInvariant()" in text
    assert "sha256 = ([string]$smplerxCheckpointDigest.sha256).ToLowerInvariant()" in text
    assert "sha256 = ([string]$openPoseDigest.sha256).ToLowerInvariant()" in text
    assert "byte_count = [int64]$openPoseDigest.byte_count" in text
    assert "models_sha256 = ([string]$openPoseModelsDigest.sha256).ToLowerInvariant()" in text
    assert "models_file_count = [int64]$openPoseModelsDigest.file_count" in text
    assert "models_byte_count = [int64]$openPoseModelsDigest.byte_count" in text
    assert '"-m", "bodyrig.sith_setup", $tempReport' in text
    assert "BODYRIG_SITH_SETUP_REPORT" in text
    assert "BODYRIG_SITH_OPENPOSE_REPO" in text
    assert "BODYRIG_SITH_OPENPOSE_SHA256" in text
    assert "BODYRIG_SITH_OPENPOSE_MODELS_SHA256" in text
    assert "BODYRIG_SITH_RECON_CHECKPOINT_SHA256" in text
    assert "BODYRIG_SITH_SMPLX_CHECKPOINT_SHA256" in text


def test_setup_report_documentation_keeps_licensed_assets_explicit_and_checkpoint_authority():
    text = (ROOT / "docs" / "HIGH_FIDELITY_SETUP.md").read_text(encoding="utf-8")
    assert "BodyRig never downloads, redistributes or embeds them in `.mrbody`" in text
    assert "setup-high-fidelity-wsl.ps1" in text
    assert "setup-report.json" in text
    assert "`bodyrig-sith-setup` v4" in text
    assert "OpenPose executable bytes" in text
    assert "OpenPose model tree" in text
    assert "recon_model.pth" in text
    assert "save_smplerx.pth" in text
    assert "point-of-use" in text
    assert OPENPOSE_REVISION in text
    assert SITH_REVISION in text
