from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.retained_anatomy_source import (
    RECEIPT_FILENAME,
    RetainedAnatomySourceError,
    publish_retained_anatomy_source,
)
from bodyrig.sith_reconstruct import FIT_PARAM_LENGTHS
from bodyrig.sith_reconstruction_authority import (
    AUTHORITY_FILENAME,
    AUTHORITY_FORMAT,
    AUTHORITY_VERSION,
    SMPLX_FIT_PROFILE,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fit_params() -> dict[str, list[float]]:
    value = {field: [0.0] * length for field, length in FIT_PARAM_LENGTHS.items()}
    value["scale"] = [1.0]
    return value


def _source_workspace(tmp_path: Path, *, texture_name: str = "000.png", gender: str = "female") -> Path:
    workspace = tmp_path / "private-identity-workspace"
    stage = workspace / "sith-input-v1"
    smplx = stage / "smplx"
    meshes = stage / "meshes"
    images = stage / "images"
    back = stage / "back_images"
    smplx.mkdir(parents=True)
    meshes.mkdir()
    images.mkdir()
    back.mkdir()

    smplx_obj = smplx / "000_smplx.obj"
    fit = smplx / "000_fit.json"
    mesh = meshes / "000_reco.obj"
    mtl = meshes / "000.mtl"
    safe_texture_name = "000.png" if "/" in texture_name or "\\" in texture_name else texture_name
    texture = meshes / safe_texture_name

    smplx_obj.write_text("v 0 0 0\n" * 20, encoding="utf-8")
    fit.write_text(json.dumps(_fit_params()), encoding="utf-8")
    mesh.write_text("mtllib 000.mtl\n" + "v 0 0 0\n" * 20, encoding="utf-8")
    mtl.write_text(f"newmtl 000\nmap_Kd {texture_name}\n", encoding="utf-8")
    texture.write_bytes(b"\x89PNG\r\n\x1a\ntexture-bytes")

    # These are intentionally private/non-required inputs and must never be copied.
    (images / "000.png").write_bytes(b"raw-centralized-frame")
    (images / "000_keypoints.json").write_text('{"private":"keypoints"}', encoding="utf-8")
    (back / "000_000.png").write_bytes(b"private-hallucinated-back-view")
    (workspace / "raw-observation.mp4").write_bytes(b"private-observation-media")

    reconstruction = {
        "format": "bodyrig-sith-reconstruction",
        "version": 1,
        "prepared_input_sha256": "a" * 64,
        "subject_track_id": "s00-t1",
        "sith_revision": "b" * 40,
        "diffusion_model_sha256": "c" * 64,
        "diffusion_model_file_count": 1,
        "diffusion_model_byte_count": 1,
        "seed": 1337,
        "hallucination": {
            "num_validation_images": 1,
            "num_inference_steps": 50,
            "offline": True,
        },
        "reconstruction": {
            "grid_size": 300,
            "save_uv": True,
            "smplx_obj_sha256": _sha256(smplx_obj),
            "fit_params_sha256": _sha256(fit),
            "back_image_sha256": "d" * 64,
            "mesh_obj_sha256": _sha256(mesh),
            "mesh_mtl_sha256": _sha256(mtl),
            "mesh_texture_name": texture_name,
            "mesh_texture_sha256": _sha256(texture),
        },
    }
    reconstruction_path = stage / "reconstruction.json"
    reconstruction_path.write_text(json.dumps(reconstruction), encoding="utf-8")
    model_authority = {
        "format": AUTHORITY_FORMAT,
        "version": AUTHORITY_VERSION,
        "body_model_gender": gender,
        "smplx_fit_profile": SMPLX_FIT_PROFILE,
        "reconstruction_sha256": _sha256(reconstruction_path),
    }
    (stage / AUTHORITY_FILENAME).write_text(json.dumps(model_authority), encoding="utf-8")
    return workspace


def test_publish_retains_only_component_bytes_family_authority_and_privacy_receipt(tmp_path: Path) -> None:
    source = _source_workspace(tmp_path, gender="female")
    output = tmp_path / "portable-output" / "retained-anatomy-source"

    receipt = publish_retained_anatomy_source(source, output)

    expected = {
        RECEIPT_FILENAME,
        "sith-input-v1/reconstruction.json",
        f"sith-input-v1/{AUTHORITY_FILENAME}",
        "sith-input-v1/smplx/000_smplx.obj",
        "sith-input-v1/smplx/000_fit.json",
        "sith-input-v1/meshes/000_reco.obj",
        "sith-input-v1/meshes/000.mtl",
        "sith-input-v1/meshes/000.png",
    }
    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*")
        if path.is_file()
    }
    assert actual == expected
    assert receipt["body_model_gender"] == "female"
    assert receipt["smplx_fit_profile"] == SMPLX_FIT_PROFILE
    assert receipt["reconstruction_authority_sha256"] == _sha256(output / "sith-input-v1" / AUTHORITY_FILENAME)
    assert receipt["raw_observation_media_retained"] is False
    assert receipt["prepared_input_retained"] is False
    assert receipt["back_view_retained"] is False
    assert receipt["reconstruction_rerun"] is False
    assert receipt["comparison_only"] is True
    assert receipt["human_review_required"] is True
    assert receipt["production_activation"] is False
    assert not (output / "raw-observation.mp4").exists()
    assert not (output / "sith-input-v1/images").exists()
    assert not (output / "sith-input-v1/back_images").exists()

    for relative, expected_hash in receipt["files"].items():
        assert _sha256(output / relative) == expected_hash


def test_publish_fails_closed_if_bound_reconstruction_bytes_changed(tmp_path: Path) -> None:
    source = _source_workspace(tmp_path)
    output = tmp_path / "retained"
    smplx = source / "sith-input-v1/smplx/000_smplx.obj"
    smplx.write_text("v 9 9 9\n" * 20, encoding="utf-8")

    with pytest.raises(RetainedAnatomySourceError, match="hash mismatch"):
        publish_retained_anatomy_source(source, output)

    assert not output.exists()


def test_publish_rejects_missing_or_mismatched_model_family_authority(tmp_path: Path) -> None:
    source = _source_workspace(tmp_path)
    output = tmp_path / "retained"
    authority_path = source / "sith-input-v1" / AUTHORITY_FILENAME
    authority_path.unlink()
    with pytest.raises(RetainedAnatomySourceError, match="model-family authority is missing"):
        publish_retained_anatomy_source(source, output)
    assert not output.exists()

    source = _source_workspace(tmp_path / "second")
    output = tmp_path / "retained-second"
    authority_path = source / "sith-input-v1" / AUTHORITY_FILENAME
    value = json.loads(authority_path.read_text(encoding="utf-8"))
    value["reconstruction_sha256"] = "9" * 64
    authority_path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(RetainedAnatomySourceError, match="does not bind current reconstruction"):
        publish_retained_anatomy_source(source, output)
    assert not output.exists()


def test_publish_rejects_unsafe_texture_reference_before_copy(tmp_path: Path) -> None:
    source = _source_workspace(tmp_path, texture_name="../escape.png")
    output = tmp_path / "retained"

    with pytest.raises(RetainedAnatomySourceError, match="safe leaf filename"):
        publish_retained_anatomy_source(source, output)

    assert not output.exists()


def test_publish_is_create_only_and_never_deletes_preexisting_destination(tmp_path: Path) -> None:
    source = _source_workspace(tmp_path)
    output = tmp_path / "retained"
    output.mkdir()
    marker = output / "operator-owned.txt"
    marker.write_bytes(b"keep me")

    with pytest.raises(RetainedAnatomySourceError, match="refusing overwrite"):
        publish_retained_anatomy_source(source, output)

    assert marker.read_bytes() == b"keep me"


def test_publish_refuses_destination_inside_private_workspace(tmp_path: Path) -> None:
    source = _source_workspace(tmp_path)
    output = source / "retained-anatomy-source"

    with pytest.raises(RetainedAnatomySourceError, match="outside the private identity workspace"):
        publish_retained_anatomy_source(source, output)

    assert not output.exists()
