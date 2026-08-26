from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _script() -> str:
    return (ROOT / "setup-recovery-windows.ps1").read_text(encoding="utf-8")


def _bridge() -> str:
    return (ROOT / "bodyrig" / "bridges" / "hmr2_4dhumans_bridge.py").read_text(encoding="utf-8")


def test_recovery_uses_wsl_cuda_matched_python_environment() -> None:
    text = _script()

    assert '[string]$Distribution = "Ubuntu-22.04"' in text
    assert '$CudaRoot = "/usr/local/cuda-11.7"' in text
    assert '"-m", "venv", $envPath' in text
    assert '"torch==2.0.1+cu117"' in text
    assert '"torchvision==0.15.2+cu117"' in text
    assert 'https://download.pytorch.org/whl/cu117' in text
    assert '"numpy==1.23.5"' in text
    assert '"opencv-python==4.8.1.78"' in text
    assert 'CUDA_HOME=$CudaRoot' in text
    assert 'FORCE_CUDA=1' in text


def test_wsl_source_builds_are_pinned_and_disable_build_isolation() -> None:
    text = _script()

    assert '$Detectron2Revision = "a2f4a8771ab77e8411c26b27f24f9489a28a2453"' in text
    assert '$ChumpyRevision = "580566eafc9ac68b2614b64d6f7aaa84eebb70da"' in text
    assert '$NmrRevision = "e990b3c70f48d39231f607c79d76ce3db4bf7483"' in text
    assert '$NmrRemote = "https://github.com/shubham-goel/NMR.git"' in text
    assert 'detectron2 @ git+https://github.com/facebookresearch/detectron2.git@$Detectron2Revision' in text
    assert 'chumpy @ git+https://github.com/mattloper/chumpy@$ChumpyRevision' in text
    assert 'neural-renderer-pytorch @ git+$NmrRemote@$NmrRevision' in text
    assert '"MAX_JOBS=4"' in text
    assert '"--no-build-isolation", "--no-deps", "-e", $fourDPath' in text
    assert '"--no-build-isolation", "--no-deps", "-e", $phalpPath' in text


def test_wsl_recovery_requires_neural_renderer_even_when_rendering_is_disabled() -> None:
    text = _script()
    bridge = _bridge()

    assert '"render.enable=false"' in bridge
    assert "import importlib.metadata as m,json,neural_renderer" in text
    assert "assert v.get('commit_id') == '$NmrRevision'" in text
    assert "assert norm(u.get('url')) == norm('$NmrRemote')" in text
    assert 'Build pinned neural-renderer in WSL' in text
    assert '_verify_nmr_install()' in bridge


def test_wsl_recovery_publishes_linux_authority_and_wsl_preflight() -> None:
    text = _script()

    assert 'external_python = $envPython' in text
    assert 'four_d_humans_repo = $fourDPath' in text
    assert 'phalp_repo = $phalpPath' in text
    assert 'nmr_revision = $NmrRevision' in text
    assert 'nmr_remote = $NmrRemote' in text
    assert '--distribution $Distribution' in text
    assert '--wsl-exe $script:WslExe' in text
    assert 'Recovery environment: READY | WSL $Distribution' in text


def test_wsl_windows_path_translation_preserves_backslashes_for_wslpath() -> None:
    text = _script()

    assert "$escapedPath = $Path.Replace('\\', '\\\\')" in text
    assert '@("wslpath", "-a", "-u", $escapedPath)' in text
    assert 'C:\\Users\\... may arrive as C:Users...' in text


def test_wsl_runtime_is_resumable_and_pins_pkg_resources_compatible_setuptools() -> None:
    text = _script()

    assert '$SetuptoolsVersion = "80.9.0"' in text
    assert '$RuntimeMarkerName = ".bodyrig-recovery-runtime-v2"' in text
    assert 'if (-not (Test-WslPath -Path $runtimeMarker))' in text
    assert '"setuptools==$SetuptoolsVersion"' in text
    assert "import pkg_resources; print('BodyRig pkg_resources compatibility: OK')" in text
    assert 'Publish WSL recovery runtime marker' in text
    assert '$nmrProbe = Invoke-WslRaw' in text
