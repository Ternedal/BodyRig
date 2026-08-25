from pathlib import Path


def test_openpose_setup_binds_explicit_cuda_root() -> None:
    script = (Path(__file__).resolve().parents[1] / "setup-openpose-wsl.ps1").read_text(encoding="utf-8")

    assert '[string]$CudaRoot = "/usr/local/cuda-11.7"' in script
    assert '$cudaNvcc = "$CudaRoot/bin/nvcc"' in script
    assert '$cudaRuntimeHeader = "$CudaRoot/include/cuda_runtime.h"' in script
    assert 'Test-WslPath -Path $cudaNvcc' in script
    assert 'Test-WslPath -Path $cudaRuntimeHeader' in script
    assert '"-DCUDA_TOOLKIT_ROOT_DIR=$CudaRoot"' in script
    assert '"-DCUDA_NVCC_EXECUTABLE=$cudaNvcc"' in script
    assert 'which", "nvcc"' not in script
