from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _script() -> str:
    return (ROOT / "setup-recovery-windows.ps1").read_text(encoding="utf-8")


def test_recovery_conda_base_is_staged_before_pip_source_builds() -> None:
    text = _script()

    assert '"create",' in text
    assert '"--override-channels"' in text
    assert '"--channel", "pytorch"' in text
    assert '"--channel", "nvidia"' in text
    assert '"--channel", "conda-forge"' in text
    assert '"python=3.10"' in text
    assert '"pytorch-cuda=11.8"' in text
    assert '"torchvision"' in text
    assert '"pip"' in text
    assert '@("env", "create"' not in text


def test_editable_recovery_installs_disable_build_isolation() -> None:
    text = _script()

    four_d_install = '@("-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation", "-e", $fourDPath)'
    phalp_install = '@("-m", "pip", "install", "--disable-pip-version-check", "--no-build-isolation", "-e", $phalpPath)'

    assert four_d_install in text
    assert phalp_install in text
    assert "Detectron2 imports Torch from setup.py" in text
