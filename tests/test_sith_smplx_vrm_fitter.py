from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.bridges import sith_smplx_vrm_fitter as fitter


def _fit_params() -> dict[str, list[float]]:
    value = {field: [0.0] * length for field, length in fitter.FIT_PARAM_LENGTHS.items()}
    value["scale"] = [1.0]
    return value


def _request(track: str = "s00-t7") -> dict:
    return {
        "format": "bodyrig-avatar-fit-request",
        "version": 1,
        "name": "Fixture Person",
        "bodyprint": {"format": "modelrig-bodyprint", "version": 1},
        "visual_identity": {
            "format": "bodyrig-visual-identity",
            "version": 1,
            "adapter": "fixture",
            "revision": "1",
            "source_count": 1,
            "subject_track_id": track,
            "capture": {},
            "coverage": {},
            "quality": {},
            "privacy": {
                "contains_source_media": False,
                "contains_biometric_template": False,
            },
        },
    }


def _workspace(tmp_path: Path, track: str = "s00-t7") -> tuple[Path, dict]:
    workspace = tmp_path / "workspace"
    stage = workspace / "sith-input-v1"
    smplx = stage / "smplx"
    meshes = stage / "meshes"
    smplx.mkdir(parents=True)
    meshes.mkdir()

    smplx_obj = smplx / "000_smplx.obj"
    fit_params = smplx / "000_fit.json"
    mesh_obj = meshes / "000_reco.obj"
    mesh_mtl = meshes / "000.mtl"
    texture = meshes / "000.png"

    smplx_obj.write_text("v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n", encoding="utf-8")
    fit_params.write_text(json.dumps(_fit_params()), encoding="utf-8")
    mesh_obj.write_text(
        "mtllib 000.mtl\n"
        "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 0 1\n"
        "f 1/1 2/2 3/3\n",
        encoding="utf-8",
    )
    mesh_mtl.write_text("newmtl 000\nmap_Kd 000.png\n", encoding="utf-8")
    texture.write_bytes(b"\x89PNG\r\n\x1a\nfixture")

    details = {
        "grid_size": 300,
        "save_uv": True,
        "smplx_obj_sha256": hashlib.sha256(smplx_obj.read_bytes()).hexdigest(),
        "fit_params_sha256": hashlib.sha256(fit_params.read_bytes()).hexdigest(),
        "back_image_sha256": "a" * 64,
        "mesh_obj_sha256": hashlib.sha256(mesh_obj.read_bytes()).hexdigest(),
        "mesh_mtl_sha256": hashlib.sha256(mesh_mtl.read_bytes()).hexdigest(),
        "mesh_texture_name": "000.png",
        "mesh_texture_sha256": hashlib.sha256(texture.read_bytes()).hexdigest(),
    }
    reconstruction = {
        "format": "bodyrig-sith-reconstruction",
        "version": 1,
        "prepared_input_sha256": "b" * 64,
        "subject_track_id": track,
        "sith_revision": "fixture",
        "diffusion_model_sha256": "c" * 64,
        "diffusion_model_file_count": 1,
        "diffusion_model_byte_count": 1,
        "seed": 1337,
        "hallucination": {"num_validation_images": 1, "num_inference_steps": 50, "offline": True},
        "reconstruction": details,
    }
    (stage / "reconstruction.json").write_text(json.dumps(reconstruction), encoding="utf-8")
    return workspace, reconstruction


def test_request_requires_exact_adapter_revision_and_private_identity(tmp_path: Path):
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(_request()), encoding="utf-8")
    request = fitter._validate_request(request_path, fitter.ADAPTER, fitter.REVISION)
    assert request["visual_identity"]["subject_track_id"] == "s00-t7"

    with pytest.raises(fitter.FitterError, match="adapter/revision mismatch"):
        fitter._validate_request(request_path, "other", fitter.REVISION)

    value = _request()
    value["visual_identity"]["privacy"]["contains_source_media"] = True
    request_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(fitter.FitterError, match="privacy boundary"):
        fitter._validate_request(request_path, fitter.ADAPTER, fitter.REVISION)


def test_workspace_rehashes_all_rigging_inputs_and_binds_subject(tmp_path: Path):
    workspace, _ = _workspace(tmp_path)
    paths = fitter._validate_workspace(workspace, _request())
    assert paths["fit_params"].name == "000_fit.json"
    assert paths["texture"].name == "000.png"

    paths["mesh_obj"].write_text(paths["mesh_obj"].read_text(encoding="utf-8") + "# tamper\n", encoding="utf-8")
    with pytest.raises(fitter.FitterError, match="mesh_obj artifact hash mismatch"):
        fitter._validate_workspace(workspace, _request())

    workspace2, _ = _workspace(tmp_path / "other", track="other-track")
    with pytest.raises(fitter.FitterError, match="subject does not match"):
        fitter._validate_workspace(workspace2, _request(track="s00-t7"))


def test_workspace_rejects_texture_path_escape(tmp_path: Path):
    workspace, reconstruction = _workspace(tmp_path)
    stage = workspace / "sith-input-v1"
    reconstruction["reconstruction"]["mesh_texture_name"] = "../escape.png"
    (stage / "reconstruction.json").write_text(json.dumps(reconstruction), encoding="utf-8")
    with pytest.raises(fitter.FitterError, match="leaf filename"):
        fitter._validate_workspace(workspace, _request())


def test_textured_obj_parser_requires_positive_triangular_position_uv_binding(tmp_path: Path):
    path = tmp_path / "mesh.obj"
    path.write_text(
        "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 0 1\n"
        "f 1/1 2/2 3/3\n",
        encoding="utf-8",
    )
    positions, uvs, faces = fitter._parse_textured_obj(path)
    assert len(positions) == 3
    assert len(uvs) == 3
    assert faces == [[(0, 0), (1, 1), (2, 2)]]

    path.write_text(
        "v 0 0 0\nv 1 0 0\nv 0 1 0\n"
        "vt 0 0\nvt 1 0\nvt 0 1\n"
        "f -1/1 2/2 3/3\n",
        encoding="utf-8",
    )
    with pytest.raises(fitter.FitterError, match="positive range"):
        fitter._parse_textured_obj(path)


def test_vrm_humanoid_mapping_covers_required_bones_with_unique_nodes():
    required = {
        "hips", "spine", "head",
        "leftUpperLeg", "leftLowerLeg", "leftFoot",
        "rightUpperLeg", "rightLowerLeg", "rightFoot",
        "leftUpperArm", "leftLowerArm", "leftHand",
        "rightUpperArm", "rightLowerArm", "rightHand",
    }
    assert required.issubset(fitter.VRM_HUMANOID)
    assert len(set(fitter.VRM_HUMANOID.values())) == len(fitter.VRM_HUMANOID)
    assert max(fitter.VRM_HUMANOID.values()) < len(fitter.SMPLX_JOINT_NAMES)


def test_fit_parameter_contract_rejects_unexpected_or_invalid_scale(tmp_path: Path):
    path = tmp_path / "fit.json"
    value = _fit_params()
    path.write_text(json.dumps(value), encoding="utf-8")
    assert fitter._fit_params(path)["scale"] == [1.0]

    value["extra"] = [0.0]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(fitter.FitterError, match="fields do not match"):
        fitter._fit_params(path)

    value = _fit_params()
    value["scale"] = [0.0]
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(fitter.FitterError, match="scale is outside"):
        fitter._fit_params(path)
