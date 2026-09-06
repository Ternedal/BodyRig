from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bodyrig.subject_anatomy_workspace import (
    IDENTITY_CAPTURE_FILES,
    PREPARED_RESUME_FILES,
    stage_workspace,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _fixture(tmp_path: Path) -> tuple[Path, Path]:
    retained = tmp_path / "retained"
    stage = retained / "sith-input-v1"
    smplx = stage / "smplx" / "000_smplx.obj"
    fit = stage / "smplx" / "000_fit.json"
    mesh = stage / "meshes" / "000_reco.obj"
    mtl = stage / "meshes" / "000.mtl"
    texture = stage / "meshes" / "material0.png"

    _write(smplx, b"v 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n")
    _write(fit, b'{"retained":true}\n')
    _write(mesh, b"v 0 0 0\nv 1 0 0\nv 0 1 0\nvt 0 0\nvt 1 0\nvt 0 1\nf 1/1 2/2 3/3\n")
    _write(mtl, b"newmtl material0\nmap_Kd material0.png\n")
    _write(texture, b"retained-texture")

    for index, relative in enumerate(PREPARED_RESUME_FILES):
        _write(stage / relative, f"resume-{index}".encode("ascii"))
    for index, relative in enumerate(IDENTITY_CAPTURE_FILES):
        _write(retained / "identity-capture" / relative, f"capture-{index}".encode("ascii"))

    # A real retained workspace already has model-family authority. The candidate
    # must not reuse those authority bytes after replacing SMPL-X geometry.
    _write(stage / "reconstruction-authority.json", b"old-retained-authority")

    reconstruction = {
        "format": "bodyrig-sith-reconstruction",
        "version": 1,
        "reconstruction": {
            "mesh_texture_name": "material0.png",
            "mesh_obj_sha256": _sha(mesh),
            "mesh_mtl_sha256": _sha(mtl),
            "mesh_texture_sha256": _sha(texture),
            "smplx_obj_sha256": _sha(smplx),
            "fit_params_sha256": _sha(fit),
        },
    }
    reconstruction_path = stage / "reconstruction.json"
    reconstruction_path.write_text(json.dumps(reconstruction, sort_keys=True) + "\n", encoding="utf-8")

    refit = tmp_path / "refit"
    derived_obj = refit / "subject_smplx.obj"
    derived_fit = refit / "subject_fit.json"
    _write(derived_obj, b"v 0 0 0\nv 2 0 0\nv 0 2 0\nf 1 2 3\n")
    _write(derived_fit, b'{"derived":true}\n')
    evidence = {
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
        "retainedSmplxObjSha256": _sha(smplx),
        "retainedFitParamsSha256": _sha(fit),
        "retainedSourceMeshSha256": _sha(mesh),
        "derivedSmplxObjSha256": _sha(derived_obj),
        "derivedFitParamsSha256": _sha(derived_fit),
        "derivedScale": 1.02,
        "derivedBetas": [0.1] * 10,
        "derivedTransl": [0.01, -0.02, 0.03],
    }
    (refit / "subject-anatomy-refit.json").write_text(
        json.dumps(evidence, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return retained, refit


def test_subject_anatomy_candidate_preserves_resume_closure_byte_for_byte(tmp_path: Path) -> None:
    retained, refit = _fixture(tmp_path)
    candidate = tmp_path / "candidate"

    receipt = stage_workspace(
        retained_workspace=retained,
        refit_dir=refit,
        output_workspace=candidate,
    )

    for relative in PREPARED_RESUME_FILES:
        assert _sha(candidate / "sith-input-v1" / relative) == _sha(retained / "sith-input-v1" / relative)
    for relative in IDENTITY_CAPTURE_FILES:
        assert _sha(candidate / "identity-capture" / relative) == _sha(retained / "identity-capture" / relative)

    assert receipt["retainedPreparedResumeBytesPreserved"] is True
    assert receipt["retainedIdentityCaptureBytesPreserved"] is True
    assert receipt["reconstructionRerun"] is False
    assert receipt["comparisonOnly"] is True
    assert receipt["productionReady"] is False

    assert _sha(candidate / "sith-input-v1" / "smplx" / "000_smplx.obj") == _sha(refit / "subject_smplx.obj")
    assert _sha(candidate / "sith-input-v1" / "smplx" / "000_fit.json") == _sha(refit / "subject_fit.json")
    assert (candidate / "sith-input-v1" / "reconstruction-authority.json").read_bytes() != b"old-retained-authority"
