from pathlib import Path


def _script() -> str:
    return (Path(__file__).resolve().parents[1] / "setup-openpose-wsl.ps1").read_text(encoding="utf-8")


def test_openpose_setup_binds_explicit_cuda_root() -> None:
    script = _script()

    assert '[string]$CudaRoot = "/usr/local/cuda-11.7"' in script
    assert '$cudaNvcc = "$CudaRoot/bin/nvcc"' in script
    assert '$cudaRuntimeHeader = "$CudaRoot/include/cuda_runtime.h"' in script
    assert 'Test-WslPath -Path $cudaNvcc' in script
    assert 'Test-WslPath -Path $cudaRuntimeHeader' in script
    assert '"-DCUDA_TOOLKIT_ROOT_DIR=$CudaRoot"' in script
    assert '"-DCUDA_NVCC_EXECUTABLE=$cudaNvcc"' in script
    assert 'which", "nvcc"' not in script


def test_openpose_wsl_capture_uses_exit_code_without_runtime_specific_argument_list() -> None:
    script = _script()

    assert '$ErrorActionPreference = "Continue"' in script
    assert '$PSNativeCommandUseErrorActionPreference = $false' in script
    assert '$output = & $WslExe -d $Distribution -- @Arguments 2>&1' in script
    assert '$exitCode = $LASTEXITCODE' in script
    assert 'ExitCode = $exitCode' in script
    assert '[System.Diagnostics.ProcessStartInfo]::new()' not in script
    assert '.ArgumentList' not in script
