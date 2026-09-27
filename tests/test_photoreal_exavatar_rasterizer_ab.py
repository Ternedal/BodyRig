from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "photoreal_exavatar_prepare_rasterizer_ab.py"


def _load_tool():
    spec = importlib.util.spec_from_file_location(
        "bodyrig_test_rasterizer_ab_builder",
        TOOL,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_rasterizer_ab_builder_patches_only_documented_conic_coefficient() -> None:
    tool = _load_tool()
    raw = "prefix\n" + tool.ORIGINAL + "\nsuffix\n"

    patched = tool._patch_backward_source(raw)

    assert tool.ORIGINAL not in patched
    assert patched.count(tool.PATCHED) == 1
    assert patched == "prefix\n" + tool.PATCHED + "\nsuffix\n"


def test_rasterizer_ab_builder_fails_closed_on_marker_drift() -> None:
    tool = _load_tool()

    with pytest.raises(
        tool.RasterizerABError,
        match="marker changed or is ambiguous",
    ):
        tool._patch_backward_source("changed upstream\n")


def test_rasterizer_ab_builder_is_pinned_and_nonproduction() -> None:
    source = TOOL.read_text(encoding="utf-8")

    compile(source, "<rasterizer-ab-builder>", "exec")
    assert "03f0b7d00383d6e96c22b37325ac9e5450947bf5" in source
    assert "74064838bc2383b187fc68693bc95f5df68309a6" in source
    assert '"HEAD^{tree}"' in source
    assert '"source_tree": EXPECTED_TREE' in source
    assert "graphdeco-inria/diff-gaussian-rasterization#94" in source
    assert "Incorrect Gradient for Off-Diagonal Conic Term" in source
    assert 'UPSTREAM_REFERENCE_STATE = "open"' in source
    assert "UPSTREAM_REFERENCE_MAINTAINER_CONFIRMED = False" in source
    assert "CANDIDATE_ONLY = True" in source
    assert '"production_activation": False' in source
    assert "build_ext" in source
    assert "--inplace" in source
    assert "staging.replace(destination)" in source
    assert '"ls-files", "-z"' in source
    assert "shutil.copytree(source, staging)" not in source
    assert '"tracked_file_count": tracked_file_count' in source
    assert "git" in source
    assert '"diff", "--quiet", "HEAD", "--"' in source
    assert '"diff", "--cached", "--quiet", "--"' in source
    assert "tracked modifications" in source
    assert "diff_gaussian_rasterization_depth._C" in source
    assert "extension_import_relative_path" in source
    assert "imported extension outside staged repo" in source
    assert "existing rasterizer A/B import origin does not match receipt" in source
    assert "VERSION = 4" in source
    assert "_clear_staged_build_artifacts(staging)" in source
    assert 'package.glob("_C*.so")' in source
    assert '"fresh_build_artifacts": True' in source
    assert '"build_environment": build_environment' in source
    assert "_build_environment_fingerprint(env)" in source
    assert "CUDA_HOME is required" in source
    assert "CUDACXX is required" in source
    assert "nvcc_version_sha256" in source
    assert "torch_cuda_version" in source
    assert "imported extension does not match built extension" in source
    assert "receipt extension paths disagree" in source


def test_rasterizer_ab_powershell_operator_is_single_launcher() -> None:
    wrapper = (
        ROOT / "prepare-photoreal-exavatar-rasterizer-ab.ps1"
    ).read_text(encoding="utf-8")

    assert wrapper.count("& wsl.exe") == 1
    assert "diag/exavatar-scene-scale-current-main-20260927" in wrapper
    assert "status --porcelain" in wrapper
    assert "refs/remotes/origin/$diagnosticBranch^{commit}" in wrapper
    assert "merge-base --is-ancestor" in wrapper
    assert wrapper.count("photoreal_exavatar_prepare_rasterizer_ab.py") == 1
    assert "Original rasterizer mutation: FALSE" in wrapper
    assert "Production: FALSE" in wrapper

def test_rasterizer_ab_build_environment_fingerprint_is_explicit(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    tool = _load_tool()
    fake_torch = SimpleNamespace(
        __version__="2.4.1+cu124",
        version=SimpleNamespace(cuda="12.4", git_version="torch-git"),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setattr(
        tool,
        "_nvcc_fingerprint",
        lambda _value: {
            "cudacxx": "/usr/local/cuda-12.4/bin/nvcc",
            "nvcc_version_sha256": "a" * 64,
            "nvcc_version_last_line": "Cuda compilation tools, release 12.4",
        },
    )

    result = tool._build_environment_fingerprint(
        {
            "CUDA_HOME": "/usr/local/cuda-12.4",
            "CUDACXX": "/usr/local/cuda-12.4/bin/nvcc",
        }
    )

    assert result["torch_version"] == "2.4.1+cu124"
    assert result["torch_cuda_version"] == "12.4"
    assert result["torch_git_version"] == "torch-git"
    assert result["cuda_home"].endswith("/usr/local/cuda-12.4")
    assert result["cudacxx"] == "/usr/local/cuda-12.4/bin/nvcc"
    assert result["nvcc_version_sha256"] == "a" * 64

