from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from .sith_reconstruction_authority import (
    AUTHORITY_FILENAME as RECONSTRUCTION_AUTHORITY_FILENAME,
    SithReconstructionAuthorityError,
    write_reconstruction_authority,
)
from .subject_anatomy_provenance import (
    SubjectAnatomyProvenanceError,
    load_subject_anatomy_refit,
    sha256_path,
)


FORMAT = "bodyrig-subject-anatomy-workspace"
VERSION = 1
IDENTITY_CAPTURE_FILES = (
    Path("capture.json"),
    Path("primary-rgb.png"),
    Path("primary-rgba.png"),
)
PREPARED_RESUME_FILES = (
    Path("stage.json"),
    Path("prep.json"),
    Path("rgba") / "000.png",
    Path("images") / "000.png",
    Path("images") / "000_keypoints.json",
    Path("back_images") / "000_000.png",
)


class SubjectAnatomyWorkspaceError(ValueError):
    pass


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise SubjectAnatomyWorkspaceError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise SubjectAnatomyWorkspaceError(f"{label} must be an object")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise SubjectAnatomyWorkspaceError(f"retained workspace artifact is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    if _sha256(source) != _sha256(destination):
        raise SubjectAnatomyWorkspaceError(f"candidate workspace copy hash mismatch: {source.name}")


def _closure_state(root: Path, relatives: tuple[Path, ...], *, label: str) -> bool:
    present = [relative for relative in relatives if (root / relative).is_file()]
    if present and len(present) != len(relatives):
        missing = [relative.as_posix() for relative in relatives if relative not in present]
        raise SubjectAnatomyWorkspaceError(
            f"retained {label} is incomplete; missing: {', '.join(missing)}"
        )
    return len(present) == len(relatives)


def _copy_identity_capture(retained_workspace: Path, output_workspace: Path) -> bool:
    retained_capture = retained_workspace / "identity-capture"
    if not retained_capture.exists():
        return False
    if not retained_capture.is_dir():
        raise SubjectAnatomyWorkspaceError("retained identity-capture path is not a directory")
    if not _closure_state(retained_capture, IDENTITY_CAPTURE_FILES, label="identity-capture closure"):
        return False
    candidate_capture = output_workspace / "identity-capture"
    candidate_capture.mkdir(parents=True, exist_ok=False)
    for relative in IDENTITY_CAPTURE_FILES:
        _copy(retained_capture / relative, candidate_capture / relative)
    return True


def stage_workspace(*, retained_workspace: Path, refit_dir: Path, output_workspace: Path) -> dict[str, Any]:
    retained_workspace = retained_workspace.expanduser().resolve()
    refit_dir = refit_dir.expanduser().resolve()
    output_workspace = output_workspace.expanduser().resolve()
    if output_workspace.exists():
        raise SubjectAnatomyWorkspaceError(f"candidate anatomy workspace already exists: {output_workspace}")

    retained_stage = retained_workspace / "sith-input-v1"
    parent_reconstruction_path = retained_stage / "reconstruction.json"
    retained_smplx = retained_stage / "smplx" / "000_smplx.obj"
    retained_fit = retained_stage / "smplx" / "000_fit.json"
    source_mesh = retained_stage / "meshes" / "000_reco.obj"
    source_mtl = retained_stage / "meshes" / "000.mtl"
    refit_evidence_path = refit_dir / "subject-anatomy-refit.json"
    derived_smplx = refit_dir / "subject_smplx.obj"
    derived_fit = refit_dir / "subject_fit.json"

    if not retained_stage.is_dir():
        raise SubjectAnatomyWorkspaceError("retained SiTH input stage is missing")
    if not parent_reconstruction_path.is_file():
        raise SubjectAnatomyWorkspaceError("retained reconstruction evidence is missing")
    try:
        evidence = load_subject_anatomy_refit(refit_evidence_path, require_non_regression=True)
    except SubjectAnatomyProvenanceError as exc:
        raise SubjectAnatomyWorkspaceError(str(exc)) from exc

    parent_sha = sha256_path(parent_reconstruction_path)
    if evidence["reconstructionSha256"] != parent_sha:
        raise SubjectAnatomyWorkspaceError("subject anatomy refit does not bind the retained reconstruction")
    retained_bindings = {
        retained_smplx: evidence["retainedSmplxObjSha256"],
        retained_fit: evidence["retainedFitParamsSha256"],
        source_mesh: evidence["retainedSourceMeshSha256"],
    }
    for path, expected in retained_bindings.items():
        if not path.is_file() or sha256_path(path) != expected:
            raise SubjectAnatomyWorkspaceError(f"subject anatomy refit retained-byte binding failed: {path.name}")
    if not derived_smplx.is_file() or sha256_path(derived_smplx) != evidence["derivedSmplxObjSha256"]:
        raise SubjectAnatomyWorkspaceError("derived subject SMPL-X OBJ does not match refit evidence")
    if not derived_fit.is_file() or sha256_path(derived_fit) != evidence["derivedFitParamsSha256"]:
        raise SubjectAnatomyWorkspaceError("derived subject fit params do not match refit evidence")

    parent_reconstruction = _read_json(parent_reconstruction_path, label="retained reconstruction evidence")
    details = parent_reconstruction.get("reconstruction")
    if not isinstance(details, dict):
        raise SubjectAnatomyWorkspaceError("retained reconstruction detail block is missing")
    texture_name = details.get("mesh_texture_name")
    if not isinstance(texture_name, str) or not texture_name.strip() or Path(texture_name).name != texture_name:
        raise SubjectAnatomyWorkspaceError("retained reconstruction texture reference is invalid")
    source_texture = retained_stage / "meshes" / texture_name
    if not source_mtl.is_file() or not source_texture.is_file():
        raise SubjectAnatomyWorkspaceError("retained source appearance artifacts are incomplete")

    source_hashes_before = {
        "mesh": sha256_path(source_mesh),
        "mtl": sha256_path(source_mtl),
        "texture": sha256_path(source_texture),
    }
    if source_hashes_before["mesh"] != str(details.get("mesh_obj_sha256", "")).lower():
        raise SubjectAnatomyWorkspaceError("retained source mesh does not match reconstruction evidence")
    if source_hashes_before["mtl"] != str(details.get("mesh_mtl_sha256", "")).lower():
        raise SubjectAnatomyWorkspaceError("retained source material does not match reconstruction evidence")
    if source_hashes_before["texture"] != str(details.get("mesh_texture_sha256", "")).lower():
        raise SubjectAnatomyWorkspaceError("retained source texture does not match reconstruction evidence")

    prepared_resume_present = _closure_state(
        retained_stage,
        PREPARED_RESUME_FILES,
        label="prepared SiTH resume closure",
    )
    retained_capture = retained_workspace / "identity-capture"
    capture_present = False
    if retained_capture.exists():
        if not retained_capture.is_dir():
            raise SubjectAnatomyWorkspaceError("retained identity-capture path is not a directory")
        capture_present = _closure_state(
            retained_capture,
            IDENTITY_CAPTURE_FILES,
            label="identity-capture closure",
        )
    if prepared_resume_present != capture_present:
        raise SubjectAnatomyWorkspaceError(
            "retained SiTH resume closure must contain both prepared input and canonical identity capture"
        )

    created = False
    try:
        candidate_stage = output_workspace / "sith-input-v1"
        created = True
        shutil.copytree(retained_stage, candidate_stage)

        identity_capture_preserved = _copy_identity_capture(retained_workspace, output_workspace)

        candidate_smplx_dir = candidate_stage / "smplx"
        candidate_mesh_dir = candidate_stage / "meshes"
        reconstruction_authority_path = candidate_stage / RECONSTRUCTION_AUTHORITY_FILENAME
        reconstruction_authority_path.unlink(missing_ok=True)

        _copy(derived_smplx, candidate_smplx_dir / "000_smplx.obj")
        _copy(derived_fit, candidate_smplx_dir / "000_fit.json")

        candidate_reconstruction = json.loads(json.dumps(parent_reconstruction))
        candidate_details = candidate_reconstruction["reconstruction"]
        candidate_details["smplx_obj_sha256"] = evidence["derivedSmplxObjSha256"]
        candidate_details["fit_params_sha256"] = evidence["derivedFitParamsSha256"]
        candidate_reconstruction_path = candidate_stage / "reconstruction.json"
        candidate_reconstruction_path.write_text(
            json.dumps(candidate_reconstruction, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )

        try:
            reconstruction_authority = write_reconstruction_authority(
                output_workspace,
                body_model_gender=evidence["targetModelFamily"],
            )
        except SithReconstructionAuthorityError as exc:
            raise SubjectAnatomyWorkspaceError(
                f"candidate reconstruction model-family authority failed: {exc}"
            ) from exc
        if reconstruction_authority.get("reconstruction_sha256") != sha256_path(candidate_reconstruction_path):
            raise SubjectAnatomyWorkspaceError(
                "candidate reconstruction authority does not bind candidate reconstruction bytes"
            )

        candidate_source_hashes = {
            "mesh": sha256_path(candidate_mesh_dir / "000_reco.obj"),
            "mtl": sha256_path(candidate_mesh_dir / "000.mtl"),
            "texture": sha256_path(candidate_mesh_dir / texture_name),
        }
        retained_source_hashes_after = {
            "mesh": sha256_path(source_mesh),
            "mtl": sha256_path(source_mtl),
            "texture": sha256_path(source_texture),
        }
        if candidate_source_hashes != source_hashes_before:
            raise SubjectAnatomyWorkspaceError("candidate workspace changed retained source appearance bytes")
        if retained_source_hashes_after != source_hashes_before or sha256_path(parent_reconstruction_path) != parent_sha:
            raise SubjectAnatomyWorkspaceError("retained reconstruction/source bytes changed while staging candidate workspace")

        prepared_resume_preserved = False
        if prepared_resume_present:
            prepared_resume_preserved = all(
                sha256_path(retained_stage / relative) == sha256_path(candidate_stage / relative)
                for relative in PREPARED_RESUME_FILES
            )
            if not prepared_resume_preserved or not identity_capture_preserved:
                raise SubjectAnatomyWorkspaceError("candidate workspace did not preserve the retained SiTH resume closure")
            for relative in IDENTITY_CAPTURE_FILES:
                if sha256_path(retained_capture / relative) != sha256_path(output_workspace / "identity-capture" / relative):
                    raise SubjectAnatomyWorkspaceError("candidate workspace changed retained identity-capture bytes")

        receipt = {
            "format": FORMAT,
            "version": VERSION,
            "parentReconstructionSha256": parent_sha,
            "candidateReconstructionSha256": sha256_path(candidate_reconstruction_path),
            "candidateReconstructionAuthoritySha256": sha256_path(reconstruction_authority_path),
            "subjectAnatomyRefitSha256": sha256_path(refit_evidence_path),
            "targetModelFamily": evidence["targetModelFamily"],
            "derivedSmplxObjSha256": evidence["derivedSmplxObjSha256"],
            "derivedFitParamsSha256": evidence["derivedFitParamsSha256"],
            "retainedSourceMeshSha256": source_hashes_before["mesh"],
            "retainedSourceMaterialSha256": source_hashes_before["mtl"],
            "retainedSourceTextureSha256": source_hashes_before["texture"],
            "retainedSourceAppearanceBytesPreserved": True,
            "retainedPreparedResumeBytesPreserved": prepared_resume_preserved,
            "retainedIdentityCaptureBytesPreserved": identity_capture_preserved,
            "retainedReconstructionModified": False,
            "reconstructionRerun": False,
            "comparisonOnly": True,
            "humanReviewRequired": True,
            "productionReady": False,
        }
        receipt_path = output_workspace / "subject-anatomy-workspace.json"
        receipt_path.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        return receipt
    except Exception:
        if created:
            shutil.rmtree(output_workspace, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage a comparison-only workspace using a subject anatomy refit.")
    parser.add_argument("--retained-workspace", required=True)
    parser.add_argument("--refit-dir", required=True)
    parser.add_argument("--output-workspace", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = stage_workspace(
            retained_workspace=Path(args.retained_workspace),
            refit_dir=Path(args.refit_dir),
            output_workspace=Path(args.output_workspace),
        )
    except (OSError, ValueError, SubjectAnatomyWorkspaceError) as exc:
        print(f"BodyRig subject anatomy workspace: FAIL: {exc}")
        return 1
    print(
        "BodyRig subject anatomy workspace: PASS | "
        f"family={receipt['targetModelFamily']} | "
        f"candidate_reconstruction={receipt['candidateReconstructionSha256']} | "
        f"resume_closure={str(receipt['retainedPreparedResumeBytesPreserved']).lower()} | "
        "reconstruction_rerun=false | production=false"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
