from __future__ import annotations

import hashlib
import json
import struct
from pathlib import Path

import pytest

import bodyrig.sith_reconstruct as reconstruct
from bodyrig.sith_input import stage_sith_input


def _png(width: int, height: int, tail: bytes) -> bytes:
    return b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", width, height) + tail


def _points(count: int, confidence: float = 0.9) -> list[float]:
    values: list[float] = []
    for index in range(count):
        values.extend((100.0 + index, 200.0 + index, confidence))
    return values


def _keypoints() -> dict:
    return {
        "version": 1.3,
        "people": [
            {
                "pose_keypoints_2d": _points(25),
                "hand_left_keypoints_2d": _points(21),
                "hand_right_keypoints_2d": _points(21),
                "face_keypoints_2d": _points(70),
            }
        ],
    }


def _fit_params() -> dict[str, list[float]]:
    values = {field: [0.0] * length for field, length in reconstruct.FIT_PARAM_LENGTHS.items()}
    values["scale"] = [1.0]
    return values


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "identity-workspace"
    capture = workspace / "identity-capture"
    capture.mkdir(parents=True)
    rgb = capture / "primary-rgb.png"
    rgba = capture / "primary-rgba.png"
    rgb.write_bytes(_png(1280, 1920, b"rgb"))
    rgba.write_bytes(_png(1280, 1920, b"rgba"))
    capture_manifest = {
        "format": "bodyrig-private-identity-capture",
        "version": 1,
        "adapter": "opencv-identity-rgba",
        "revision": "1",
        "subject_track_id": "s00-t7",
        "primary": {
            "rgb": "primary-rgb.png",
            "rgba": "primary-rgba.png",
            "rgb_sha256": hashlib.sha256(rgb.read_bytes()).hexdigest(),
            "rgba_sha256": hashlib.sha256(rgba.read_bytes()).hexdigest(),
            "source_index": 0,
            "time_seconds": 1.25,
            "foreground_fraction": 0.42,
        },
    }
    (capture / "capture.json").write_text(json.dumps(capture_manifest), encoding="utf-8")
    stage, _ = stage_sith_input(workspace)
    image = stage / "images" / "000.png"
    keypoint_path = stage / "images" / "000_keypoints.json"
    image.write_bytes(_png(1024, 1024, b"centralized"))
    keypoint_path.write_text(json.dumps(_keypoints()), encoding="utf-8")
    stage_sha = hashlib.sha256((stage / "stage.json").read_bytes()).hexdigest()
    prep = {
        "format": "bodyrig-sith-prepared-input",
        "version": 1,
        "stage_manifest_sha256": stage_sha,
        "subject_track_id": "s00-t7",
        "sith_revision": reconstruct.SITH_REVISION,
        "centralizer_blob": reconstruct.SITH_CENTRALIZE_RGBA_BLOB,
        "centralized_image_sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
        "openpose_keypoints_sha256": hashlib.sha256(keypoint_path.read_bytes()).hexdigest(),
        "centralized_size": [1024, 1024],
        "openpose_quality": {
            "body_confident": 25,
            "left_hand_confident": 21,
            "right_hand_confident": 21,
            "face_confident": 70,
        },
    }
    (stage / "prep.json").write_text(json.dumps(prep), encoding="utf-8")
    return workspace


def _write_reconstruction_fixture(stage: Path) -> None:
    (stage / "smplx" / "000_smplx.obj").write_text("v 0 0 0\n" * 20, encoding="utf-8")
    (stage / "smplx" / "000_fit.json").write_text(json.dumps(_fit_params()), encoding="utf-8")
    (stage / "back_images" / "000_000.png").write_bytes(_png(512, 512, b"back"))
    meshes = stage / "meshes"
    (meshes / "000_reco.obj").write_text("mtllib 000.mtl\n" + "v 0 0 0\n" * 20, encoding="utf-8")
    (meshes / "000.mtl").write_text("newmtl 000\nmap_Kd 000.png\n", encoding="utf-8")
    (meshes / "000.png").write_bytes(_png(1024, 1024, b"texture"))


def test_load_prepared_input_rehashes_image_and_keypoints(tmp_path: Path):
    workspace = _workspace(tmp_path)
    stage, prep, prep_sha = reconstruct.load_prepared_input(workspace)
    assert stage.name == "sith-input-v1"
    assert prep["subject_track_id"] == "s00-t7"
    assert len(prep_sha) == 64

    (stage / "images" / "000.png").write_bytes(_png(1024, 1024, b"tampered"))
    with pytest.raises(reconstruct.SithReconstructError, match="image byte hash mismatch"):
        reconstruct.load_prepared_input(workspace)


def test_validate_fit_params_is_strict_and_finite(tmp_path: Path):
    path = tmp_path / "000_fit.json"
    path.write_text(json.dumps(_fit_params()), encoding="utf-8")
    result = reconstruct.validate_fit_params(path)
    assert result["scale"] == [1.0]
    assert len(result["body_pose"]) == 63

    invalid = _fit_params()
    invalid["unexpected"] = [0.0]
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(reconstruct.SithReconstructError, match="fields must match"):
        reconstruct.validate_fit_params(path)

    invalid = _fit_params()
    invalid["scale"] = [0.0]
    path.write_text(json.dumps(invalid), encoding="utf-8")
    with pytest.raises(reconstruct.SithReconstructError, match="scale is outside"):
        reconstruct.validate_fit_params(path)


def test_validate_reconstruction_outputs_binds_obj_fit_mtl_texture(tmp_path: Path):
    stage = tmp_path / "stage"
    (stage / "smplx").mkdir(parents=True)
    (stage / "back_images").mkdir()
    (stage / "meshes").mkdir()
    _write_reconstruction_fixture(stage)

    result = reconstruct.validate_reconstruction_outputs(stage)
    assert result["mesh_texture_name"] == "000.png"
    assert len(result["mesh_obj_sha256"]) == 64
    assert result["fit_params_sha256"] == hashlib.sha256((stage / "smplx" / "000_fit.json").read_bytes()).hexdigest()

    (stage / "meshes" / "000.mtl").write_text("newmtl 000\nmap_Kd ../escape.png\n", encoding="utf-8")
    with pytest.raises(reconstruct.SithReconstructError, match="leaf filename"):
        reconstruct.validate_reconstruction_outputs(stage)


def test_reconstruct_runs_fit_canonicalization_offline_hallucination_and_uv_reconstruction(monkeypatch, tmp_path: Path):
    workspace = _workspace(tmp_path)
    stage = workspace / "sith-input-v1"
    commands = []
    expected_model = "b" * 64

    monkeypatch.setattr(reconstruct, "verify_execution_authority", lambda **kwargs: None)

    def fake_linux_path(path, **kwargs):
        path = Path(path)
        if path.name == "sith_canonical_smplx_obj.py":
            return "/mnt/c/bodyrig/bridges/sith_canonical_smplx_obj.py"
        return "/mnt/c/private/sith-input-v1"

    monkeypatch.setattr(reconstruct, "_linux_path", fake_linux_path)
    monkeypatch.setattr(
        reconstruct,
        "digest_model_tree",
        lambda **kwargs: {"sha256": expected_model, "file_count": 12, "byte_count": 999999},
    )

    def fake_checked_wsl(*, command, label, cwd=None, **kwargs):
        command = list(command)
        commands.append((label, cwd, command))
        if label == "SiTH SMPL-X fitting":
            smplx = stage / "smplx"
            (smplx / "000_smplx.obj").write_text("v 0 0 0\n" * 20, encoding="utf-8")
            debug = smplx / "debug"
            debug.mkdir()
            (debug / "000.json").write_text(json.dumps(_fit_params()), encoding="utf-8")
            return ""
        if label == "BodyRig canonical SMPL-X OBJ":
            (stage / "smplx" / "000_smplx.obj").write_text("v 1 0 0\n" * 20, encoding="utf-8")
            return ""
        if label == "SiTH offline back-view hallucination":
            (stage / "back_images" / "000_000.png").write_bytes(_png(512, 512, b"back"))
            (stage / "back_images" / "all_images").mkdir()
            return ""
        if label == "SiTH textured UV reconstruction":
            meshes = stage / "meshes"
            (meshes / "000_reco.obj").write_text("mtllib 000.mtl\n" + "v 0 0 0\n" * 20, encoding="utf-8")
            (meshes / "000.mtl").write_text("newmtl 000\nmap_Kd 000.png\n", encoding="utf-8")
            (meshes / "000.png").write_bytes(_png(1024, 1024, b"texture"))
            return ""
        raise AssertionError(f"unexpected command: {label}")

    monkeypatch.setattr(reconstruct, "_checked_wsl", fake_checked_wsl)
    evidence = reconstruct.reconstruct_sith(
        workspace=workspace,
        distribution="Ubuntu-22.04",
        repo="/opt/sith",
        python="/opt/sith/.venv/bin/python",
        diffusion_model="/opt/models/sith-diffusion",
        diffusion_model_sha256=expected_model,
    )

    assert [item[0] for item in commands] == [
        "SiTH SMPL-X fitting",
        "BodyRig canonical SMPL-X OBJ",
        "SiTH offline back-view hallucination",
        "SiTH textured UV reconstruction",
    ]
    for _, cwd, _ in commands:
        assert cwd == "/opt/sith"

    fit = commands[0][2]
    assert fit[1] == "fit.py"
    assert "--opt_orient" in fit and "--opt_betas" in fit and "--debug" in fit
    assert sorted(path.name for path in (stage / "smplx").iterdir()) == ["000_fit.json", "000_smplx.obj"]
    assert reconstruct.validate_fit_params(stage / "smplx" / "000_fit.json")["scale"] == [1.0]
    assert (stage / "smplx" / "000_smplx.obj").read_text(encoding="utf-8").startswith("v 1 0 0")

    canonical = commands[1][2]
    assert canonical[1] == "/mnt/c/bodyrig/bridges/sith_canonical_smplx_obj.py"
    assert canonical[canonical.index("--smplx-model-dir") + 1] == "/opt/sith/data/body_models/smplx"
    assert canonical[canonical.index("--fit-params") + 1] == "/mnt/c/private/sith-input-v1/smplx/000_fit.json"
    assert canonical[canonical.index("--output") + 1] == "/mnt/c/private/sith-input-v1/smplx/000_smplx.obj"

    hallucinate = commands[2][2]
    assert hallucinate[:4] == [
        "/usr/bin/env",
        "HF_HUB_OFFLINE=1",
        "TRANSFORMERS_OFFLINE=1",
        "HF_DATASETS_OFFLINE=1",
    ]
    assert hallucinate[hallucinate.index("--pretrained_model_name_or_path") + 1] == "/opt/models/sith-diffusion"
    assert hallucinate[hallucinate.index("--seed") + 1] == "1337"
    assert hallucinate[hallucinate.index("--num_validation_images") + 1] == "1"

    uv = commands[3][2]
    assert "--save_uv" in uv
    assert uv[uv.index("--grid_size") + 1] == "300"
    assert uv[uv.index("--test_folder") + 1] == "/mnt/c/private/sith-input-v1"

    assert evidence["diffusion_model_sha256"] == expected_model
    assert evidence["seed"] == 1337
    assert evidence["hallucination"]["offline"] is True
    assert evidence["reconstruction"]["save_uv"] is True
    assert evidence["reconstruction"]["fit_params_sha256"] == hashlib.sha256((stage / "smplx" / "000_fit.json").read_bytes()).hexdigest()
    persisted = json.loads((stage / "reconstruction.json").read_text(encoding="utf-8"))
    assert persisted == evidence
    assert "/opt/" not in json.dumps(evidence)
    assert "/mnt/" not in json.dumps(evidence)


def test_reconstruct_rejects_model_digest_mismatch_before_research_commands(monkeypatch, tmp_path: Path):
    workspace = _workspace(tmp_path)
    calls = []
    monkeypatch.setattr(reconstruct, "verify_execution_authority", lambda **kwargs: None)
    monkeypatch.setattr(
        reconstruct,
        "digest_model_tree",
        lambda **kwargs: {"sha256": "c" * 64, "file_count": 1, "byte_count": 1},
    )
    monkeypatch.setattr(reconstruct, "_checked_wsl", lambda **kwargs: calls.append(kwargs))

    with pytest.raises(reconstruct.SithReconstructError, match="tree digest mismatch"):
        reconstruct.reconstruct_sith(
            workspace=workspace,
            distribution="Ubuntu-22.04",
            repo="/opt/sith",
            python="/opt/sith/.venv/bin/python",
            diffusion_model="/opt/models/sith-diffusion",
            diffusion_model_sha256="b" * 64,
        )
    assert calls == []
