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


def test_source_builds_disable_build_isolation() -> None:
    text = _script()

    assert '"--no-build-isolation", "-e", $fourDPath' in text
    assert '"detectron2 @ git+https://github.com/facebookresearch/detectron2.git"' in text
    assert '"--no-build-isolation", "--no-deps", "-e", $phalpPath' in text
    assert "Detectron2 imports Torch from setup.py" in text


def test_windows_recovery_omits_unused_phalp_neural_renderer() -> None:
    text = _script()

    assert 'render.enable=false' in text
    assert 'install the pinned PHALP checkout with --no-deps' in text
    assert '"scenedetect[opencv]"' in text
    assert '"pyopengl @ git+https://github.com/mmatl/pyopengl.git"' in text
    assert '"chumpy @ git+https://github.com/mattloper/chumpy"' in text
    assert 'neural-renderer-pytorch' in text  # rationale comment only

    command_section = text[text.index('Invoke-Checked -Executable $envPython -Arguments @(', text.index('Install pinned 4D-Humans checkout')):]
    command_section = command_section[: command_section.index('$smplDestination')]
    assert '"neural-renderer-pytorch' not in command_section
