from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any

import sith_anatomy_texture_bake as anatomy_bake
import sith_smplx_vrm_fitter as base


FORMAT = "bodyrig-exact-anatomy-bake-score"
VERSION = 1
METHOD = "production-anatomy-bake-exact-geometry-score-v1"
RESOLUTION = 1024
GENDERS = ("female", "male", "neutral")


class ExactAnatomyBakeScoreError(ValueError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise ExactAnatomyBakeScoreError(f"required scoring artifact is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: Path, *, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ExactAnatomyBakeScoreError(f"{label} is missing")
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExactAnatomyBakeScoreError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise ExactAnatomyBakeScoreError(f"{label} must be an object")
    return value


def _retained_source_paths(workspace: Path) -> tuple[Path, Path, Path, str]:
    stage = workspace / "sith-input-v1"
    reconstruction_path = stage / "reconstruction.json"
    reconstruction = _read_json(reconstruction_path, label="retained SiTH reconstruction evidence")
    details = reconstruction.get("reconstruction")
    if not isinstance(details, dict):
        raise ExactAnatomyBakeScoreError("retained SiTH reconstruction details are missing")

    required = {
        "grid_size",
        "save_uv",
        "smplx_obj_sha256",
        "fit_params_sha256",
        "back_image_sha256",
        "mesh_obj_sha256",
        "mesh_mtl_sha256",
        "mesh_texture_name",
        "mesh_texture_sha256",
    }
    if set(details) != required or details.get("grid_size") != 300 or details.get("save_uv") is not True:
        raise ExactAnatomyBakeScoreError("retained SiTH reconstruction is not the pinned UV authority")

    texture_name = details.get("mesh_texture_name")
    if not isinstance(texture_name, str) or not texture_name or Path(texture_name).name != texture_name:
        raise ExactAnatomyBakeScoreError("retained SiTH texture reference is invalid")

    mesh = stage / "meshes" / "000_reco.obj"
    mtl = stage / "meshes" / "000.mtl"
    texture = stage / "meshes" / texture_name
    expected = {
        mesh: details.get("mesh_obj_sha256"),
        mtl: details.get("mesh_mtl_sha256"),
        texture: details.get("mesh_texture_sha256"),
    }
    for path, digest in expected.items():
        if not isinstance(digest, str) or len(digest) != 64 or _sha256(path) != digest.lower():
            raise ExactAnatomyBakeScoreError(f"retained source hash mismatch: {path.name}")
    if not texture.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"):
        raise ExactAnatomyBakeScoreError("retained source texture is not PNG")
    return reconstruction_path, mesh, texture, texture_name


def _finite_metric(metrics: dict[str, Any], key: str) -> float:
    value = metrics.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExactAnatomyBakeScoreError(f"exact anatomy bake metric is missing: {key}")
    result = float(value)
    if not math.isfinite(result):
        raise ExactAnatomyBakeScoreError(f"exact anatomy bake metric is non-finite: {key}")
    return result


def build_receipt(
    *,
    donor_sha256: str,
    reconstruction_sha256: str,
    source_mesh_sha256: str,
    source_texture_sha256: str,
    gender: str,
    metrics: dict[str, Any],
) -> dict[str, Any]:
    for label, digest in (
        ("donor", donor_sha256),
        ("reconstruction", reconstruction_sha256),
        ("source mesh", source_mesh_sha256),
        ("source texture", source_texture_sha256),
    ):
        if not isinstance(digest, str) or len(digest) != 64:
            raise ExactAnatomyBakeScoreError(f"{label} SHA-256 is invalid")
    if gender not in GENDERS:
        raise ExactAnatomyBakeScoreError("SMPL-X scoring gender is invalid")

    body_scale = _finite_metric(metrics, "body_scale")
    p95 = _finite_metric(metrics, "bake_surface_distance_p95")
    maximum = _finite_metric(metrics, "bake_surface_distance_max")
    normal_mean = _finite_metric(metrics, "normal_alignment_mean")
    normal_p05 = _finite_metric(metrics, "normal_alignment_p05")
    low_ratio = _finite_metric(metrics, "normal_low_alignment_ratio")
    retry_ratio = _finite_metric(metrics, "normal_retry_texel_ratio")
    occupied = _finite_metric(metrics, "bake_occupied_ratio")
    padded = _finite_metric(metrics, "bake_padded_texel_ratio")
    if body_scale <= 0.0 or p95 < 0.0 or maximum < 0.0:
        raise ExactAnatomyBakeScoreError("exact anatomy bake distance metrics are invalid")
    if not -1.0 <= normal_mean <= 1.0 or not -1.0 <= normal_p05 <= 1.0:
        raise ExactAnatomyBakeScoreError("exact anatomy bake normal metrics are invalid")
    if any(not 0.0 <= value <= 1.0 for value in (low_ratio, retry_ratio, occupied, padded)):
        raise ExactAnatomyBakeScoreError("exact anatomy bake ratio metrics are invalid")

    return {
        "format": FORMAT,
        "version": VERSION,
        "method": METHOD,
        "resolution": RESOLUTION,
        "gender": gender,
        "donorSha256": donor_sha256,
        "reconstructionSha256": reconstruction_sha256,
        "sourceMeshSha256": source_mesh_sha256,
        "sourceTextureSha256": source_texture_sha256,
        "metrics": {
            "body_scale": body_scale,
            "surface_distance_p95": p95,
            "surface_distance_max": maximum,
            "surface_distance_p95_body_ratio": p95 / body_scale,
            "surface_distance_max_body_ratio": maximum / body_scale,
            "normal_alignment_mean": normal_mean,
            "normal_alignment_p05": normal_p05,
            "normal_low_alignment_ratio": low_ratio,
            "normal_retry_texel_ratio": retry_ratio,
            "occupied_texel_ratio": occupied,
            "padded_texel_ratio": padded,
        },
        "sourceDerived": True,
        "exactProductionBakePath": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "humanFidelityPass": False,
        "productionReady": False,
        "reconstructionRerun": False,
    }


def score(
    *,
    sith_repo: Path,
    model_dir: Path,
    workspace: Path,
    donor_obj: Path,
    gender: str,
    output_file: Path,
) -> dict[str, Any]:
    if gender not in GENDERS:
        raise ExactAnatomyBakeScoreError("SMPL-X scoring gender is invalid")
    repo = sith_repo.expanduser().resolve()
    models = model_dir.expanduser().resolve()
    retained_workspace = workspace.expanduser().resolve()
    donor = donor_obj.expanduser().resolve()
    output = output_file.expanduser().resolve()
    if not repo.is_dir() or not (repo / "data" / "smplx_uv.obj").is_file():
        raise ExactAnatomyBakeScoreError("pinned SiTH scoring repository is missing")
    if not models.is_dir():
        raise ExactAnatomyBakeScoreError("licensed SMPL-X model directory is missing")
    if not retained_workspace.is_dir():
        raise ExactAnatomyBakeScoreError("retained identity workspace is missing")
    if not donor.is_file():
        raise ExactAnatomyBakeScoreError("donor OBJ is missing")
    if output.exists():
        raise ExactAnatomyBakeScoreError(f"score output already exists: {output}")

    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    try:
        import numpy as np
        import torch
        from smplx import SMPLX
    except ImportError as exc:
        raise ExactAnatomyBakeScoreError(f"exact anatomy bake scoring dependencies are unavailable: {exc}") from exc
    if not torch.cuda.is_available():
        raise ExactAnatomyBakeScoreError("exact anatomy bake scoring requires CUDA")

    reconstruction_path, source_mesh, source_texture, _texture_name = _retained_source_paths(retained_workspace)
    donor_positions = np.asarray(base._parse_positions(donor), dtype=np.float32)
    if donor_positions.ndim != 2 or donor_positions.shape[1] != 3:
        raise ExactAnatomyBakeScoreError("donor OBJ positions are invalid")

    device = torch.device("cuda")
    model = None
    try:
        model = SMPLX(
            model_path=str(models),
            gender=gender,
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        ).to(device)
        model.eval()
        raw_faces = getattr(model, "faces", None)
        if raw_faces is None:
            raw_faces = getattr(model, "faces_tensor", None)
        if raw_faces is None:
            raise ExactAnatomyBakeScoreError("licensed SMPL-X model exposes no face topology")
        values = raw_faces.detach().cpu().tolist() if hasattr(raw_faces, "detach") else raw_faces.tolist()
        donor_faces = [[int(item) for item in row] for row in values]
        if not donor_faces or any(len(face) != 3 for face in donor_faces):
            raise ExactAnatomyBakeScoreError("licensed SMPL-X face topology is invalid")
        if max(max(face) for face in donor_faces) >= int(donor_positions.shape[0]):
            raise ExactAnatomyBakeScoreError("donor OBJ does not match licensed SMPL-X topology")

        _texcoords, _bound_faces, _baked_png, metrics = anatomy_bake.bake_sith_surface_to_anatomy_canonical_smplx(
            torch=torch,
            np=np,
            donor_positions=donor_positions,
            donor_faces=donor_faces,
            sith_repo=repo,
            source_mesh_obj=source_mesh,
            source_texture_path=source_texture,
            model_dir=models,
            gender=gender,
            device=device,
            resolution=RESOLUTION,
        )
    except anatomy_bake.AnatomyTextureBakeError as exc:
        raise ExactAnatomyBakeScoreError(f"production anatomy bake scoring failed: {exc}") from exc
    finally:
        del model
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    receipt = build_receipt(
        donor_sha256=_sha256(donor),
        reconstruction_sha256=_sha256(reconstruction_path),
        source_mesh_sha256=_sha256(source_mesh),
        source_texture_sha256=_sha256(source_texture),
        gender=gender,
        metrics=dict(metrics),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sith-repo", required=True)
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--bodyrig-workspace", required=True)
    parser.add_argument("--donor-obj", required=True)
    parser.add_argument("--gender", required=True, choices=GENDERS)
    parser.add_argument("--output-file", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = score(
            sith_repo=Path(args.sith_repo),
            model_dir=Path(args.smplx_model_dir),
            workspace=Path(args.bodyrig_workspace),
            donor_obj=Path(args.donor_obj),
            gender=args.gender,
            output_file=Path(args.output_file),
        )
        metrics = receipt["metrics"]
        print(
            "BodyRig exact anatomy bake score: PASS | "
            f"p95_ratio={float(metrics['surface_distance_p95_body_ratio']):.6f} | "
            f"max_ratio={float(metrics['surface_distance_max_body_ratio']):.6f} | "
            f"normal_mean={float(metrics['normal_alignment_mean']):.6f} | "
            f"normal_p05={float(metrics['normal_alignment_p05']):.6f} | "
            f"low={float(metrics['normal_low_alignment_ratio']):.6f} | "
            f"retry={float(metrics['normal_retry_texel_ratio']):.6f}"
        )
        return 0
    except Exception as exc:
        print(f"BodyRig exact anatomy bake score: FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
