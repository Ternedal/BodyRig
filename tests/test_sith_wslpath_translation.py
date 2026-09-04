from __future__ import annotations

from pathlib import Path

import pytest

import bodyrig.sith_fitter_orchestrator as orchestrator
import bodyrig.sith_prepare as prepare
import bodyrig.sith_reconstruct as reconstruct
from bodyrig.wsl_adapter_bridge import WslBridgeError


def _bind_converter(monkeypatch, module, *, expected: str = "/mnt/c/Users/admin/AppData/Local/BodyRig/identity-workspaces/run/sith-input-v1"):
    calls: list[tuple[str, ...]] = []

    def fake_factory(wsl_exe: str, distribution: str):
        calls.append(("factory", wsl_exe, distribution))

        def convert(value: str) -> str:
            calls.append(("convert", value))
            return expected

        return convert

    monkeypatch.setattr(module, "make_wsl_path_converter", fake_factory)
    return calls


@pytest.mark.parametrize(
    ("module", "helper"),
    [
        (prepare, prepare._linux_path),
        (reconstruct, reconstruct._linux_path),
        (orchestrator, orchestrator._wsl_path),
    ],
)
def test_sith_windows_paths_use_shared_escaped_converter(monkeypatch, tmp_path: Path, module, helper):
    stage = tmp_path / "identity-workspaces" / "run" / "sith-input-v1"
    stage.mkdir(parents=True)
    calls = _bind_converter(monkeypatch, module)

    value = helper(stage, wsl_exe="wsl.exe", distribution="Ubuntu-22.04")

    assert value == "/mnt/c/Users/admin/AppData/Local/BodyRig/identity-workspaces/run/sith-input-v1"
    assert calls[0] == ("factory", "wsl.exe", "Ubuntu-22.04")
    assert calls[1][0] == "convert"
    assert calls[1][1] == str(stage.resolve())


@pytest.mark.parametrize(
    ("module", "helper", "error_type"),
    [
        (prepare, prepare._linux_path, prepare.SithPrepareError),
        (reconstruct, reconstruct._linux_path, reconstruct.SithReconstructError),
        (orchestrator, orchestrator._wsl_path, orchestrator.SithFitterOrchestratorError),
    ],
)
def test_sith_path_translation_wraps_shared_converter_errors(monkeypatch, tmp_path: Path, module, helper, error_type):
    stage = tmp_path / "sith-input-v1"
    stage.mkdir()

    def fake_factory(wsl_exe: str, distribution: str):
        def convert(value: str) -> str:
            raise WslBridgeError("wslpath failed for BodyRig path: fixture")

        return convert

    monkeypatch.setattr(module, "make_wsl_path_converter", fake_factory)

    with pytest.raises(error_type, match="WSL path translation failed"):
        helper(stage, wsl_exe="wsl.exe", distribution="Ubuntu-22.04")
