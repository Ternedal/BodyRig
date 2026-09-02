from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bodyrig.subject_anatomy_workspace import SubjectAnatomyWorkspaceError, stage_workspace


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    retained = tmp_path / "retained"
    stage = retained / "sith-input-v1"
    retained_smplx = stage / "smplx" / "000_smplx.obj"
    retained_fit = stage / "smplx" / "000_fit.json"
    source_mesh = stage / "meshes" / "000_reco.obj"
    source_mtl = stage / "meshes" / "000.mtl"
    texture = stage / "meshes" / "material0.png"
    _write(retained_smplx, b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    _write(retained_fit, b"{\"retained\":true}\n")
    _write(source_mesh, b"v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n")
    _write(source_mtl, b"newmtl material0\nmap_Kd material0.png\n")
    _write(texture, b"fake-png-source-bytes")

    reconstruction = {
        "format": "bodyrig-sith-reconstruction",
        "version": 1,
        "reconstruction": {
            "mesh_texture_name": "material0.png",
            "mesh_obj_sha256": _sha(source_mesh),
            "mesh_mtl_sha256": _sha(source_mtl),
            "mesh_texture_sha256": _sha(texture),
            "smplx_obj_sha256": _sha(retained_smplx),
            "fit_params_sha256": _sha(retained_fit),
        },
    }
    reconstruction_path = stage / "reconstruction.json"
    reconstruction_path.write_text(json.dumps(reconstruction, sort_keys=True) + "\n", encoding="utf-8")

    refit = tmp_path / "refit"
    derived_smplx = refit / "subject_smplx.obj"
    derived_fit = refit / "subject_fit.json"
    _write(derived_smplx, b"v 0 0 0\nv 2 0 0\nv 0 2 0\nf 1 2 3\n")
    _write(derived_fit, b"{\"derived\":true}\n")
    receipt = {
        "format": "bodyrig-subject-anatomy-refit",
        "version": 1,
        "targetModelFamily": "female",
        "method": "explicit-family-smplx-betas-icp-to-retained-sith-source-v1",
        "initialDonorToSourceP95": 0.08,
        "initialDonorToSourceRms": 0.04,
        "finalDonorToSourceP95": 0.05,
        "finalDonorToSourceRms": 0.025,
        "iterations": 120,
        "fitDidNotRegress": True,
        "poseAuthority": "retained-sith-fit",
        "shapeAuthority": "derived-target-family-fit-to-retained-source",
        "retainedReconstructionModified": False,
        "reconstructionRerun": False,
        "generativeGeometry": False,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
        "reconstructionSha256": _sha(reconstruction_path),
        "retainedSmplxObjSha256": _sha(retained_smplx),
        "retainedFitParamsSha256": _sha(retained_fit),
        "retainedSourceMeshSha256": _sha(source_mesh),
        "derivedSmplxObjSha256": _sha(derived_smplx),
        "derivedFitParamsSha256": _sha(derived_fit),
        "derivedScale": 1.02,
        "derivedBetas": [0.1] * 10,
        "derivedTransl": [0.01, -0.02, 0.03],
    }
    (refit / "subject-anatomy-refit.json").write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
    return retained, refit


def test_stage_subject_anatomy_workspace_changes_only_smplx_authority(tmp_path) -> None:
    retained, refit = _fixture(tmp_path)
    output = tmp_path / "candidate"
    parent_reconstruction = retained / "sith-input-v1" / "reconstruction.json"
    parent_sha_before = _sha(parent_reconstruction)

    receipt = stage_workspace(retained_workspace=retained, refit_dir=refit, output_workspace=output)

    candidate_stage = output / "sith-input-v1"
    candidate_reconstruction = json.loads((candidate_stage / "reconstruction.json").read_text(encoding="utf-8"))
    assert candidate_reconstruction["reconstruction"]["smplx_obj_sha256"] == _sha(refit / "subject_smplx.obj")
    assert candidate_reconstruction["reconstruction"]["fit_params_sha256"] == _sha(refit / "subject_fit.json")
    assert _sha(candidate_stage / "meshes" / "000_reco.obj") == _sha(retained / "sith-input-v1" / "meshes" / "000_reco.obj")
    assert _sha(candidate_stage / "meshes" / "000.mtl") == _sha(retained / "sith-input-v1" / "meshes" / "000.mtl")
    assert _sha(candidate_stage / "meshes" / "material0.png") == _sha(retained / "sith-input-v1" / "meshes" / "material0.png")
    assert _sha(parent_reconstruction) == parent_sha_before
    assert receipt["retainedSourceAppearanceBytesPreserved"] is True
    assert receipt["reconstructionRerun"] is False
    assert receipt["productionReady"] is False


def test_stage_subject_anatomy_workspace_rejects_unbound_derived_obj(tmp_path) -> None:
    retained, refit = _fixture(tmp_path)
    (refit / "subject_smplx.obj").write_text("v 9 9 9\n", encoding="utf-8")

    with pytest.raises(SubjectAnatomyWorkspaceError, match="derived subject SMPL-X OBJ"):
        stage_workspace(
            retained_workspace=retained,
            refit_dir=refit,
            output_workspace=tmp_path / "candidate",
        )
