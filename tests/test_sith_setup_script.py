from __future__ import annotations

from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "setup-sith-wsl.ps1"


def _text() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def test_setup_pins_sith_and_never_invokes_command_shell() -> None:
    text = _text()
    assert '6401549120a4a6246b5cb4a10d8c3e1b2d9e8c7d' in text
    assert 'https://github.com/SiTH-Diffusion/SiTH.git' in text
    assert '"checkout", "--detach", $SithRevision' in text
    assert 'bash", "-c"' not in text
    assert 'bash", "-lc"' not in text
    assert 'sh", "-c"' not in text
    assert 'sh", "-lc"' not in text


def test_setup_requires_all_six_local_smplx_assets() -> None:
    text = _text()
    for leaf in (
        "SMPLX_NEUTRAL.pkl",
        "SMPLX_NEUTRAL.npz",
        "SMPLX_MALE.pkl",
        "SMPLX_MALE.npz",
        "SMPLX_FEMALE.pkl",
        "SMPLX_FEMALE.npz",
    ):
        assert f'"{leaf}"' in text
    assert 'Required SMPL-X source asset missing' in text


def test_public_checkpoint_download_is_explicit_and_direct() -> None:
    text = _text()
    assert '[switch]$DownloadPublicCheckpoints' in text
    assert 'if ($DownloadPublicCheckpoints)' in text
    assert 'https://files.ait.ethz.ch/projects/SiTH/recon_model.pth' in text
    assert 'https://files.ait.ethz.ch/projects/SiTH/save_smplerx.pth' in text
    assert '"wget", "--https-only"' in text
    assert 'tools/download.sh' not in text


def test_setup_exports_exact_builtin_stash_settings() -> None:
    text = _text()
    expected = {
        "BODYRIG_SITH_DISTRIBUTION",
        "BODYRIG_SITH_REPO",
        "BODYRIG_SITH_PYTHON",
        "BODYRIG_SITH_OPENPOSE",
        "BODYRIG_SITH_DIFFUSION_MODEL",
        "BODYRIG_SITH_DIFFUSION_SHA256",
    }
    for name in expected:
        assert name in text
    assert '[switch]$PersistUserEnvironment' in text
    assert 'SetEnvironmentVariable' in text


def test_setup_finishes_through_same_preflight_and_model_digest_as_clone() -> None:
    text = _text()
    assert '"-m", "bodyrig.sith_preflight"' in text
    assert '"-m", "bodyrig.sith_model"' in text
    assert 'SiTH final preflight failed' in text
    assert 'SiTH diffusion model digest failed' in text
