from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import bodyrig.sith_fitter_orchestrator as orchestrator


def _boundary(tmp_path: Path) -> tuple[Path, Path, Path]:
    request = tmp_path / "request.json"
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    request.write_text("{}", encoding="utf-8")
    workspace.mkdir()
    output.mkdir()
    return request, workspace, output


def _bind_checkpoint_authority(monkeypatch, *, recon: str = "d" * 64, smplerx: str = "e" * 64):
    monkeypatch.setenv(orchestrator.RECON_CHECKPOINT_HASH_ENV, recon)
    monkeypatch.setenv(orchestrator.SMPLX_CHECKPOINT_HASH_ENV, smplerx)

    def fake_digest_wsl_file(*, path: str, **kwargs):
        if path.endswith("/recon_model.pth"):
            return {"sha256": recon, "byte_count": 10}
        if path.endswith("/save_smplerx.pth"):
            return {"sha256": smplerx, "byte_count": 20}
        raise AssertionError(f"unexpected checkpoint path: {path}")

    monkeypatch.setattr(orchestrator, "digest_wsl_file", fake_digest_wsl_file)


def test_orchestrator_runs_private_stages_then_wsl_rig_bridge(monkeypatch, tmp_path: Path):
    request, workspace, output = _boundary(tmp_path)
    _bind_checkpoint_authority(monkeypatch)
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        orchestrator,
        "stage_sith_input",
        lambda value: calls.append(("stage", Path(value))) or (Path(value) / "sith-input-v1", {}),
    )
    monkeypatch.setattr(
        orchestrator,
        "prepare_sith_input",
        lambda **kwargs: calls.append(("prepare", kwargs)) or {},
    )
    monkeypatch.setattr(
        orchestrator,
        "reconstruct_sith",
        lambda **kwargs: calls.append(("reconstruct", kwargs)) or {},
    )

    translations: list[Path] = []

    def fake_wsl_path(path, **kwargs):
        resolved = Path(path).resolve()
        translations.append(resolved)
        return "/mnt/c/" + resolved.name

    monkeypatch.setattr(orchestrator, "_wsl_path", fake_wsl_path)
    invocations: list[list[str]] = []

    def fake_run(command, **kwargs):
        invocations.append(list(command))
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(orchestrator, "_run", fake_run)

    orchestrator.orchestrate_sith_fitter(
        request=request,
        workspace=workspace,
        output=output,
        adapter=orchestrator.ADAPTER,
        revision=orchestrator.REVISION,
        distribution="Ubuntu-22.04",
        sith_repo="/opt/sith",
        sith_python="/opt/sith/.venv/bin/python",
        openpose="/opt/openpose/build/examples/openpose/openpose.bin",
        diffusion_model="/opt/models/sith-diffusion",
        diffusion_model_sha256="a" * 64,
    )

    assert [name for name, _ in calls] == ["stage", "prepare", "reconstruct"]
    prepare = calls[1][1]
    assert isinstance(prepare, dict)
    assert prepare["workspace"] == workspace.resolve()
    assert prepare["repo"] == "/opt/sith"
    reconstruct = calls[2][1]
    assert isinstance(reconstruct, dict)
    assert reconstruct["diffusion_model_sha256"] == "a" * 64
    assert reconstruct["seed"] == orchestrator.DEFAULT_SEED

    assert len(invocations) == 1
    invocation = invocations[0]
    assert invocation[:5] == [
        "wsl.exe",
        "-d",
        "Ubuntu-22.04",
        "--",
        "/opt/sith/.venv/bin/python",
    ]
    assert invocation[invocation.index("--smplx-model-dir") + 1] == "/opt/sith/data/body_models/smplx"
    assert invocation[invocation.index("--bodyrig-adapter") + 1] == orchestrator.ADAPTER
    assert invocation[invocation.index("--bodyrig-revision") + 1] == orchestrator.REVISION
    assert request.resolve() in translations
    assert workspace.resolve() in translations
    assert output.resolve() in translations


def test_orchestrator_rejects_checkpoint_tamper_before_private_work(monkeypatch, tmp_path: Path):
    request, workspace, output = _boundary(tmp_path)
    _bind_checkpoint_authority(monkeypatch, recon="d" * 64, smplerx="e" * 64)
    monkeypatch.setattr(
        orchestrator,
        "digest_wsl_file",
        lambda **kwargs: {"sha256": "f" * 64, "byte_count": 10},
    )
    calls: list[str] = []
    monkeypatch.setattr(orchestrator, "stage_sith_input", lambda *_: calls.append("stage"))

    with pytest.raises(orchestrator.SithFitterOrchestratorError, match="checkpoint SHA-256 mismatch"):
        orchestrator.orchestrate_sith_fitter(
            request=request,
            workspace=workspace,
            output=output,
            adapter=orchestrator.ADAPTER,
            revision=orchestrator.REVISION,
            distribution="Ubuntu-22.04",
            sith_repo="/opt/sith",
            sith_python="/opt/sith/.venv/bin/python",
            openpose="/opt/openpose/build/examples/openpose/openpose.bin",
            diffusion_model="/opt/models/sith-diffusion",
            diffusion_model_sha256="a" * 64,
        )
    assert calls == []


def test_orchestrator_requires_checkpoint_authority_before_private_work(monkeypatch, tmp_path: Path):
    request, workspace, output = _boundary(tmp_path)
    monkeypatch.delenv(orchestrator.RECON_CHECKPOINT_HASH_ENV, raising=False)
    monkeypatch.delenv(orchestrator.SMPLX_CHECKPOINT_HASH_ENV, raising=False)
    calls: list[str] = []
    monkeypatch.setattr(orchestrator, "stage_sith_input", lambda *_: calls.append("stage"))

    with pytest.raises(orchestrator.SithFitterOrchestratorError, match="setup-bound lowercase SHA-256"):
        orchestrator.orchestrate_sith_fitter(
            request=request,
            workspace=workspace,
            output=output,
            adapter=orchestrator.ADAPTER,
            revision=orchestrator.REVISION,
            distribution="Ubuntu-22.04",
            sith_repo="/opt/sith",
            sith_python="/opt/sith/.venv/bin/python",
            openpose="/opt/openpose/build/examples/openpose/openpose.bin",
            diffusion_model="/opt/models/sith-diffusion",
            diffusion_model_sha256="a" * 64,
        )
    assert calls == []


def test_orchestrator_rejects_adapter_drift_before_private_work(monkeypatch, tmp_path: Path):
    request, workspace, output = _boundary(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(orchestrator, "stage_sith_input", lambda *_: calls.append("stage"))
    monkeypatch.setattr(orchestrator, "prepare_sith_input", lambda **_: calls.append("prepare"))
    monkeypatch.setattr(orchestrator, "reconstruct_sith", lambda **_: calls.append("reconstruct"))

    with pytest.raises(orchestrator.SithFitterOrchestratorError, match="adapter/revision mismatch"):
        orchestrator.orchestrate_sith_fitter(
            request=request,
            workspace=workspace,
            output=output,
            adapter="wrong-adapter",
            revision=orchestrator.REVISION,
            distribution="Ubuntu-22.04",
            sith_repo="/opt/sith",
            sith_python="/opt/sith/.venv/bin/python",
            openpose="/opt/openpose/build/examples/openpose/openpose.bin",
            diffusion_model="/opt/models/sith-diffusion",
            diffusion_model_sha256="a" * 64,
        )
    assert calls == []


def test_orchestrator_requires_linux_research_paths_before_staging(monkeypatch, tmp_path: Path):
    request, workspace, output = _boundary(tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(orchestrator, "stage_sith_input", lambda *_: calls.append("stage"))

    with pytest.raises(orchestrator.SithFitterOrchestratorError, match="SiTH repo must be an absolute Linux path"):
        orchestrator.orchestrate_sith_fitter(
            request=request,
            workspace=workspace,
            output=output,
            adapter=orchestrator.ADAPTER,
            revision=orchestrator.REVISION,
            distribution="Ubuntu-22.04",
            sith_repo="relative/sith",
            sith_python="/opt/sith/.venv/bin/python",
            openpose="/opt/openpose/build/examples/openpose/openpose.bin",
            diffusion_model="/opt/models/sith-diffusion",
            diffusion_model_sha256="a" * 64,
        )
    assert calls == []
