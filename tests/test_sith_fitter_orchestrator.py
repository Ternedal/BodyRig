from __future__ import annotations

import json
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


def _resume_outputs() -> dict[str, str]:
    return {
        "smplx_obj_sha256": "1" * 64,
        "fit_params_sha256": "2" * 64,
        "back_image_sha256": "3" * 64,
        "mesh_obj_sha256": "4" * 64,
        "mesh_mtl_sha256": "5" * 64,
        "mesh_texture_name": "000.png",
        "mesh_texture_sha256": "6" * 64,
    }


def _resume_evidence(*, prep_sha256: str, outputs: dict[str, str], diffusion: str = "a" * 64, seed: int = 1337):
    return {
        "format": orchestrator.RECON_FORMAT,
        "version": orchestrator.RECON_VERSION,
        "prepared_input_sha256": prep_sha256,
        "subject_track_id": "track-7",
        "sith_revision": "fixture-revision",
        "diffusion_model_sha256": diffusion,
        "diffusion_model_file_count": 17,
        "diffusion_model_byte_count": 123456,
        "seed": seed,
        "hallucination": {
            "num_validation_images": 1,
            "num_inference_steps": 50,
            "offline": True,
        },
        "reconstruction": {
            "grid_size": 300,
            "save_uv": True,
            **outputs,
        },
    }


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


def test_resume_validator_accepts_exact_completed_reconstruction(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    stage = workspace / "sith-input-v1"
    stage.mkdir(parents=True)
    prep_sha = "b" * 64
    outputs = _resume_outputs()
    (stage / "reconstruction.json").write_text(
        json.dumps(_resume_evidence(prep_sha256=prep_sha, outputs=outputs)),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        orchestrator,
        "load_prepared_input",
        lambda value: (
            stage,
            {"subject_track_id": "track-7", "sith_revision": "fixture-revision"},
            prep_sha,
        ),
    )
    monkeypatch.setattr(orchestrator, "validate_reconstruction_outputs", lambda value: outputs)

    orchestrator._validate_resume_reconstruction(
        workspace,
        diffusion_model_sha256="a" * 64,
        seed=1337,
    )


def test_resume_validator_rejects_reconstruction_artifact_hash_drift(monkeypatch, tmp_path: Path):
    workspace = tmp_path / "workspace"
    stage = workspace / "sith-input-v1"
    stage.mkdir(parents=True)
    prep_sha = "b" * 64
    actual_outputs = _resume_outputs()
    recorded_outputs = dict(actual_outputs)
    recorded_outputs["mesh_obj_sha256"] = "f" * 64
    (stage / "reconstruction.json").write_text(
        json.dumps(_resume_evidence(prep_sha256=prep_sha, outputs=recorded_outputs)),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        orchestrator,
        "load_prepared_input",
        lambda value: (
            stage,
            {"subject_track_id": "track-7", "sith_revision": "fixture-revision"},
            prep_sha,
        ),
    )
    monkeypatch.setattr(orchestrator, "validate_reconstruction_outputs", lambda value: actual_outputs)

    with pytest.raises(orchestrator.SithFitterOrchestratorError, match="mesh_obj_sha256 mismatch"):
        orchestrator._validate_resume_reconstruction(
            workspace,
            diffusion_model_sha256="a" * 64,
            seed=1337,
        )


def test_orchestrator_resumes_completed_reconstruction_without_recomputing(monkeypatch, tmp_path: Path):
    request, workspace, output = _boundary(tmp_path)
    stage = workspace / "sith-input-v1"
    stage.mkdir()
    (stage / "reconstruction.json").write_text("{}", encoding="utf-8")
    _bind_checkpoint_authority(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        orchestrator,
        "_validate_resume_reconstruction",
        lambda *args, **kwargs: calls.append("resume"),
    )
    monkeypatch.setattr(orchestrator, "stage_sith_input", lambda *_: calls.append("stage"))
    monkeypatch.setattr(orchestrator, "prepare_sith_input", lambda **_: calls.append("prepare"))
    monkeypatch.setattr(orchestrator, "reconstruct_sith", lambda **_: calls.append("reconstruct"))
    monkeypatch.setattr(orchestrator, "_wsl_path", lambda path, **_: "/mnt/c/" + Path(path).name)
    invocations: list[list[str]] = []
    monkeypatch.setattr(
        orchestrator,
        "_run",
        lambda command, **_: invocations.append(list(command)) or subprocess.CompletedProcess(command, 0, "", ""),
    )

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

    assert calls == ["resume"]
    assert len(invocations) == 1


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
