from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _script() -> str:
    return (ROOT / "setup-sith-wsl.ps1").read_text(encoding="utf-8")


def test_sith_uses_upstream_cuda_121_toolchain() -> None:
    text = _script()

    assert '$SithCudaRoot = "/usr/local/cuda-12.1"' in text
    assert '"torch==2.1.0"' in text
    assert '"torchvision==0.16.0"' in text
    assert 'https://download.pytorch.org/whl/cu121' in text
    assert "torch.version.cuda == '12.1'" in text
    assert 'cuda-toolkit-12-1' in text


def test_sith_installs_torch_before_pinned_nvdiffrast_without_build_isolation() -> None:
    text = _script()

    torch_install = text.index('Install SiTH PyTorch CUDA 12.1 runtime')
    filtered_requirements = text.index('Stage SiTH requirements without nvdiffrast')
    nvdiffrast_install = text.index('Build pinned nvdiffrast against CUDA 12.1')

    assert torch_install < filtered_requirements < nvdiffrast_install
    assert '$NvdiffrastRevision = "253ac4fcea7de5f396371124af597e6cc957bfae"' in text
    assert '"--no-build-isolation"' in text
    assert 'CUDA_HOME=$SithCudaRoot' in text
    assert 'CUDACXX=$SithCudaRoot/bin/nvcc' in text


def test_sith_dependency_setup_is_resumable_and_path_translation_preserves_backslashes() -> None:
    text = _script()

    assert '$RuntimeMarkerName = ".bodyrig-sith-runtime-v2"' in text
    assert 'Publish SiTH runtime completion marker' in text
    assert 'SiTH runtime marker present; reusing completed dependency environment.' in text
    assert "$escapedPath = $Path.Replace('\\', '\\\\')" in text
    assert '@("wslpath", "-a", "-u", $escapedPath)' in text
