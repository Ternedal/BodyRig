from __future__ import annotations

from pathlib import Path

from bodyrig.sith_preflight import OPENPOSE_REVISION, SITH_REVISION


ROOT = Path(__file__).resolve().parents[1]


def test_openpose_setup_pins_revision_and_cuda_build():
    text = (ROOT / "setup-openpose-wsl.ps1").read_text(encoding="utf-8")
    assert OPENPOSE_REVISION in text
    assert '"-DGPU_MODE=CUDA"' in text
    assert '"-DDOWNLOAD_BODY_25_MODEL=ON"' in text
    assert '"-DDOWNLOAD_FACE_MODEL=ON"' in text
    assert '"-DDOWNLOAD_HAND_MODEL=ON"' in text
    assert 'build/examples/openpose/openpose.bin' in text
    assert 'hash-object", "CMakeLists.txt"' in text
    assert "sudo" not in text.lower()


def test_top_level_setup_binds_sith_openpose_and_model_report():
    text = (ROOT / "setup-high-fidelity-wsl.ps1").read_text(encoding="utf-8")
    assert SITH_REVISION in text
    assert OPENPOSE_REVISION in text
    assert "setup-openpose-wsl.ps1" in text
    assert "setup-sith-wsl.ps1" in text
    assert '"--openpose-repo", $OpenPoseRepo' in text
    assert '"-m", "bodyrig.sith_model"' in text
    assert 'format = "bodyrig-sith-setup"' in text
    assert '"-m", "bodyrig.sith_setup", $tempReport' in text
    assert "BODYRIG_SITH_SETUP_REPORT" in text
    assert "BODYRIG_SITH_OPENPOSE_REPO" in text


def test_setup_report_documentation_keeps_licensed_assets_explicit():
    text = (ROOT / "docs" / "HIGH_FIDELITY_SETUP.md").read_text(encoding="utf-8")
    assert "BodyRig never downloads, redistributes or embeds them in `.mrbody`" in text
    assert "setup-high-fidelity-wsl.ps1" in text
    assert "setup-report.json" in text
    assert OPENPOSE_REVISION in text
    assert SITH_REVISION in text
