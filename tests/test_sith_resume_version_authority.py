from __future__ import annotations

import json
from pathlib import Path

import pytest

import bodyrig.sith_fitter_orchestrator as orchestrator


INVALID_V1_VALUES = (True, False, "1", None, 2)
VALID_V1_VALUES = (1, 1.0)


def _outputs() -> dict[str, str]:
    return {
        "smplx_obj_sha256": "1" * 64,
        "fit_params_sha256": "2" * 64,
        "back_image_sha256": "3" * 64,
        "mesh_obj_sha256": "4" * 64,
        "mesh_mtl_sha256": "5" * 64,
        "mesh_texture_name": "000.png",
        "mesh_texture_sha256": "6" * 64,
    }


def _evidence(version: object, *, prep_sha256: str, outputs: dict[str, str]) -> dict[str, object]:
    return {
        "format": orchestrator.RECON_FORMAT,
        "version": version,
        "prepared_input_sha256": prep_sha256,
        "subject_track_id": "track-7",
        "sith_revision": "fixture-revision",
        "diffusion_model_sha256": "a" * 64,
        "diffusion_model_file_count": 17,
        "diffusion_model_byte_count": 123456,
        "seed": 1337,
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


def _prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: object,
) -> Path:
    workspace = tmp_path / "workspace"
    stage = workspace / "sith-input-v1"
    stage.mkdir(parents=True)
    prep_sha = "b" * 64
    outputs = _outputs()
    (stage / "reconstruction.json").write_text(
        json.dumps(_evidence(version, prep_sha256=prep_sha, outputs=outputs)),
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
    monkeypatch.setattr(orchestrator, "validate_reconstruction_authority", lambda *args, **kwargs: {})
    monkeypatch.setattr(orchestrator, "validate_reconstruction_outputs", lambda value: outputs)
    return workspace


@pytest.mark.parametrize("version", INVALID_V1_VALUES)
def test_resume_reconstruction_rejects_noncanonical_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: object,
) -> None:
    workspace = _prepare(monkeypatch, tmp_path, version)

    with pytest.raises(orchestrator.SithFitterOrchestratorError, match="format/version mismatch"):
        orchestrator._validate_resume_reconstruction(
            workspace,
            diffusion_model_sha256="a" * 64,
            seed=1337,
            body_model_gender="neutral",
        )


@pytest.mark.parametrize("version", VALID_V1_VALUES)
def test_resume_reconstruction_accepts_numeric_v1(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    version: object,
) -> None:
    workspace = _prepare(monkeypatch, tmp_path, version)

    orchestrator._validate_resume_reconstruction(
        workspace,
        diffusion_model_sha256="a" * 64,
        seed=1337,
        body_model_gender="neutral",
    )
