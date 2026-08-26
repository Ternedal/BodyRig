from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_hmr2_child_uses_physical_wsl_cuda_loader_contract() -> None:
    text = (ROOT / "bodyrig" / "bridges" / "hmr2_4dhumans_bridge.py").read_text(encoding="utf-8")

    assert 'WSL_CUDA_DRIVER_LIB = Path("/usr/lib/wsl/lib")' in text
    assert 'CUDA_TOOLKIT_LIB = Path("/usr/local/cuda-11.7/lib64")' in text
    assert 'Path(torch_file).resolve().parent / "lib"' in text
    assert 'libcudnn_cnn_infer.so.8' in text
    assert 'loader_env = _recovery_loader_env()' in text
    assert '_verify_cuda_loader_env(loader_env)' in text
    assert 'env=loader_env' in text
    assert '_run_source(repo, source, index, loader_env)' in text


def test_preflight_uses_same_wsl_loader_components() -> None:
    text = (ROOT / "bodyrig" / "preflight_cli.py").read_text(encoding="utf-8")

    assert 'WSL_CUDA_DRIVER_LIB = "/usr/lib/wsl/lib"' in text
    assert 'WSL_CUDA_TOOLKIT_LIB = "/usr/local/cuda-11.7/lib64"' in text
    assert 'pathlib.Path(torch.__file__).resolve().parent / \'lib\'' in text
    assert 'f"LD_LIBRARY_PATH={loader_path}"' in text
    assert 'ctypes.CDLL(library)' in text
    assert '"libcuda.so", "load_libcuda"' in text
    assert '"libcudnn_cnn_infer.so.8", "load_libcudnn_cnn_infer"' in text
