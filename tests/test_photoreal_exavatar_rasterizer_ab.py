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
    assert "VERSION = 3" in source
    assert "_clear_staged_build_artifacts(staging)" in source
    assert 'package.glob("_C*.so")' in source
    assert '"fresh_build_artifacts": True' in source
    assert "imported extension does not match built extension" in source
    assert "receipt extension paths disagree" in source


def test_rasterizer_ab_powershell_operator_is_single_launcher() -> None:
    wrapper = (
        ROOT / "prepare-photoreal-exavatar-rasterizer-ab.ps1"
    ).read_text(encoding="utf-8")

    assert wrapper.count("& wsl.exe") == 1
    assert "diag/exavatar-final-symlink-containment-runner" in wrapper
    assert "status --porcelain" in wrapper
    assert "refs/remotes/origin/$diagnosticBranch^{commit}" in wrapper
    assert "merge-base --is-ancestor" in wrapper
    assert wrapper.count("photoreal_exavatar_prepare_rasterizer_ab.py") == 1
    assert "Original rasterizer mutation: FALSE" in wrapper
    assert "Production: FALSE" in wrapper
