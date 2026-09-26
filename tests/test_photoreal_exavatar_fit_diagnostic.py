from pathlib import Path

import pytest

from tools import photoreal_exavatar_fit_diagnostic as diagnostic


def test_patch_fit_source_adds_first_nonfinite_guards(tmp_path: Path) -> None:
    main_dir = tmp_path / "main"
    source = (
        diagnostic.FIT_IMPORT_MARKER
        + "\n"
        + "def main():\n"
        + diagnostic.SET_ARGS_MARKER
        + "    for epoch in range(1):\n"
        + "        for itr_data in range(1):\n"
        + "            for itr_opt in range(1):\n"
        + diagnostic.LOSS_MARKER
    )

    patched = diagnostic._patch_fit_source(source, main_dir=main_dir)

    assert "bodyrig-fit-diagnostic" in patched
    assert "torch.autograd.set_detect_anomaly(True)" in patched
    assert "BodyRig fitting non-finite loss" in patched
    assert "BodyRig fitting non-finite gradient" in patched
    assert "BodyRig fitting non-finite parameter after step" in patched
    assert "_bodyrig_stable_edge_length_forward" in patched
    assert "eps = 1e-12" in patched
    assert "torch.sum(delta * delta, dim=2, keepdim=True) + eps" in patched
    assert f"_bodyrig_sys.path.insert(0, {str(main_dir)!r})" in patched
    compile(patched, "<bodyrig-fit-diagnostic>", "exec")


def test_patch_fit_source_fails_closed_on_upstream_marker_drift(tmp_path: Path) -> None:
    with pytest.raises(
        diagnostic.ExAvatarFitDiagnosticError,
        match="markers changed",
    ):
        diagnostic._patch_fit_source("print('changed')\n", main_dir=tmp_path)

def test_fit_diagnostic_powershell_wrapper_is_single_well_formed_launcher() -> None:
    wrapper = (
        Path(__file__).resolve().parents[1]
        / "run-photoreal-exavatar-fit-diagnostic.ps1"
    ).read_text(encoding="utf-8")

    assert wrapper.count("$resolvedDiagnostic =") == 1
    assert wrapper.count("$resolvedDiagnostic -notmatch") == 1
    assert wrapper.count("$linuxDiagnostic =") == 1
    assert wrapper.count("BODYRIG EXAVATAR SMPL-X FIT DIAGNOSTIC") == 1
    assert wrapper.count("& wsl.exe") == 1
    assert "'^([A-Za-z]):\\\\(.*)$'" in wrapper
    assert "$rest = $Matches[2] -replace '\\\\', '/'" in wrapper

