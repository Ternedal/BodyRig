from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

import sith_smplx_vrm_fitter as base
import sith_subject_anatomy_refit as legacy


FORMAT = legacy.FORMAT
VERSION = 1
METHOD_V3 = "explicit-family-smplx-betas-icp-bake-surface-normal-aware-to-retained-sith-source-v3"
TARGET_FAMILIES = legacy.TARGET_FAMILIES
ITERATIONS = legacy.ITERATIONS
CORRESPONDENCE_INTERVAL = legacy.CORRESPONDENCE_INTERVAL
NORMAL_LOSS_WEIGHT = 0.04
NORMAL_NONREGRESSION_TOLERANCE = 1e-4
NORMAL_ALIGNMENT_AUTHORITY = "sith-closest-source-triangle-face-normal-v1"
NORMAL_SAMPLE_METHOD = "deterministic-smplx-face-centroids-v1"
NORMAL_SAMPLE_TARGET = 4096
MIN_NORMAL_FACE_COUNT = 100


class SubjectAnatomyRefitV3Error(ValueError):
    pass


def build_receipt_v3(
    *,
    target_family: str,
    initial_p95: float,
    initial_rms: float,
    final_p95: float,
    final_rms: float,
    initial_normal_mean: float,
    initial_normal_p05: float,
    final_normal_mean: float,
    final_normal_p05: float,
    normal_sample_count: int,
    iterations: int,
) -> dict[str, Any]:
    if target_family not in TARGET_FAMILIES:
        raise SubjectAnatomyRefitV3Error("target SMPL-X model family is invalid")
    distance_values = [float(initial_p95), float(initial_rms), float(final_p95), float(final_rms)]
    if any(not math.isfinite(value) or value < 0.0 for value in distance_values):
        raise SubjectAnatomyRefitV3Error("subject anatomy v3 distance metrics are invalid")
    normal_values = [
        float(initial_normal_mean),
        float(initial_normal_p05),
        float(final_normal_mean),
        float(final_normal_p05),
    ]
    if any(not math.isfinite(value) or not -1.0 <= value <= 1.0 for value in normal_values):
        raise SubjectAnatomyRefitV3Error("subject anatomy v3 normal metrics are invalid")
    if isinstance(normal_sample_count, bool) or not isinstance(normal_sample_count, int) or normal_sample_count < MIN_NORMAL_FACE_COUNT:
        raise SubjectAnatomyRefitV3Error("subject anatomy v3 normal sample count is invalid")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise SubjectAnatomyRefitV3Error("subject anatomy v3 iteration count is invalid")

    distance_non_regression = final_p95 <= initial_p95 + 1e-9 and final_rms <= initial_rms + 1e-9
    normal_non_regression = (
        final_normal_mean + NORMAL_NONREGRESSION_TOLERANCE >= initial_normal_mean
        and final_normal_p05 + NORMAL_NONREGRESSION_TOLERANCE >= initial_normal_p05
    )
    improved = distance_non_regression and normal_non_regression
    return {
        "format": FORMAT,
        "version": VERSION,
        "targetModelFamily": target_family,
        "method": METHOD_V3,
        "initialDonorToSourceP95": round(initial_p95, 9),
        "initialDonorToSourceRms": round(initial_rms, 9),
        "finalDonorToSourceP95": round(final_p95, 9),
        "finalDonorToSourceRms": round(final_rms, 9),
        "initialNormalAlignmentMean": round(initial_normal_mean, 9),
        "initialNormalAlignmentP05": round(initial_normal_p05, 9),
        "finalNormalAlignmentMean": round(final_normal_mean, 9),
        "finalNormalAlignmentP05": round(final_normal_p05, 9),
        "normalAwareNonRegression": bool(normal_non_regression),
        "normalAlignmentAuthority": NORMAL_ALIGNMENT_AUTHORITY,
        "normalSampleMethod": NORMAL_SAMPLE_METHOD,
        "normalSampleCount": normal_sample_count,
        "normalLossWeight": NORMAL_LOSS_WEIGHT,
        "iterations": iterations,
        "fitDidNotRegress": bool(improved),
        "poseAuthority": "retained-sith-fit",
        "shapeAuthority": "derived-target-family-fit-to-retained-source",
        "retainedReconstructionModified": False,
        "reconstructionRerun": False,
        "generativeGeometry": False,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionReady": False,
    }


def _sample_face_indices(torch: Any, *, face_count: int, device: Any) -> Any:
    if isinstance(face_count, bool) or not isinstance(face_count, int) or face_count < MIN_NORMAL_FACE_COUNT:
        raise SubjectAnatomyRefitV3Error("too few donor faces for bake-aligned normal sampling")
    stride = max(1, face_count // NORMAL_SAMPLE_TARGET)
    indices = torch.arange(0, face_count, stride, dtype=torch.long, device=device)
    if int(indices.shape[0]) > NORMAL_SAMPLE_TARGET:
        indices = indices[:NORMAL_SAMPLE_TARGET]
    if int(indices.shape[0]) < MIN_NORMAL_FACE_COUNT:
        raise SubjectAnatomyRefitV3Error("too few sampled donor faces for bake-aligned normal sampling")
    return indices


def _sampled_surface(
    torch: Any,
    *,
    vertices: Any,
    donor_faces: Any,
    sample_indices: Any,
    per_face_normals: Any,
) -> tuple[Any, Any, Any]:
    faces = donor_faces[sample_indices]
    triangles = vertices[faces]
    centroids = torch.mean(triangles, dim=1)
    normals = per_face_normals(vertices, faces)
    lengths = torch.linalg.vector_norm(normals, dim=1)
    valid = torch.isfinite(lengths) & (lengths > 1e-6)
    if int(valid.sum().item()) < MIN_NORMAL_FACE_COUNT:
        raise SubjectAnatomyRefitV3Error("too few valid sampled donor faces for bake-aligned normal sampling")
    return centroids, normals, valid


def _closest_source_surface(
    torch: Any,
    *,
    query: Any,
    source: Any,
    source_faces: Any,
    closest_point_fast: Any,
    per_face_normals: Any,
) -> tuple[Any, Any, Any]:
    with torch.no_grad():
        _distance, hit_points, hit_face_indices = closest_point_fast(source, source_faces, query.detach())
        hit_face_indices = hit_face_indices.reshape(-1).long()
        if int(hit_face_indices.shape[0]) != int(query.shape[0]):
            raise SubjectAnatomyRefitV3Error("SiTH closest-surface correspondence count mismatch")
        hit_faces = source_faces[hit_face_indices]
        target_normals = per_face_normals(source, hit_faces).detach()
        hit_points = hit_points.detach()
        target_lengths = torch.linalg.vector_norm(target_normals, dim=1)
        target_valid = torch.isfinite(target_lengths) & (target_lengths > 1e-6)
    return hit_points, target_normals, target_valid


def _surface_normal_metrics(
    torch: Any,
    *,
    posed: Any,
    donor_faces: Any,
    sample_indices: Any,
    source: Any,
    source_faces: Any,
    closest_point_fast: Any,
    per_face_normals: Any,
) -> tuple[float, float]:
    centroids, donor_normals, donor_valid = _sampled_surface(
        torch,
        vertices=posed,
        donor_faces=donor_faces,
        sample_indices=sample_indices,
        per_face_normals=per_face_normals,
    )
    _hit_points, source_normals, source_valid = _closest_source_surface(
        torch,
        query=centroids,
        source=source,
        source_faces=source_faces,
        closest_point_fast=closest_point_fast,
        per_face_normals=per_face_normals,
    )
    valid = donor_valid & source_valid
    if int(valid.sum().item()) < MIN_NORMAL_FACE_COUNT:
        raise SubjectAnatomyRefitV3Error("too few valid bake-aligned normal correspondences")
    alignment = torch.clamp(torch.sum(donor_normals * source_normals, dim=1), -1.0, 1.0)
    values = alignment[valid]
    mean = float(torch.mean(values).item())
    p05 = float(torch.quantile(values, 0.05).item())
    if not math.isfinite(mean) or not math.isfinite(p05):
        raise SubjectAnatomyRefitV3Error("bake-aligned normal metrics are non-finite")
    return mean, p05


def refit_v3(
    *,
    sith_repo: Path,
    model_dir: Path,
    workspace: Path,
    target_family: str,
    output_dir: Path,
) -> dict[str, Any]:
    if target_family not in TARGET_FAMILIES:
        raise SubjectAnatomyRefitV3Error("target SMPL-X model family is invalid")
    if output_dir.exists():
        raise SubjectAnatomyRefitV3Error(f"subject anatomy v3 output already exists: {output_dir}")
    repo = sith_repo.expanduser().resolve()
    if not repo.is_dir():
        raise SubjectAnatomyRefitV3Error("SiTH repository is missing")
    if str(repo) not in sys.path:
        sys.path.insert(0, str(repo))
    try:
        import numpy as np
        import torch
        import torch.nn.functional as F
        from smplx import SMPLX
        from recon.models.ops.mesh.closest_point import closest_point_fast
        from recon.models.ops.mesh.per_face_normals import per_face_normals
    except ImportError as exc:
        raise SubjectAnatomyRefitV3Error(f"subject anatomy v3 dependencies are unavailable: {exc}") from exc
    if not torch.cuda.is_available():
        raise SubjectAnatomyRefitV3Error("subject anatomy v3 requires CUDA")

    stage = workspace.expanduser().resolve() / "sith-input-v1"
    reconstruction = stage / "reconstruction.json"
    smplx_obj = stage / "smplx" / "000_smplx.obj"
    fit_path = stage / "smplx" / "000_fit.json"
    source_path = stage / "meshes" / "000_reco.obj"
    retained_hashes = {
        "reconstructionSha256": legacy._sha256(reconstruction),
        "retainedSmplxObjSha256": legacy._sha256(smplx_obj),
        "retainedFitParamsSha256": legacy._sha256(fit_path),
        "retainedSourceMeshSha256": legacy._sha256(source_path),
    }

    retained_params = base._fit_params(fit_path)
    source_positions, _texcoords, source_faces_raw = base._parse_textured_obj(source_path)
    source_faces = [[int(corner[0]) for corner in face] for face in source_faces_raw]
    if len(source_positions) < 100 or not source_faces or any(len(face) != 3 for face in source_faces):
        raise SubjectAnatomyRefitV3Error("retained SiTH source mesh is invalid")

    device = torch.device("cuda")
    source = torch.tensor(np.asarray(source_positions, dtype=np.float32), dtype=torch.float32, device=device)
    source_faces_tensor = torch.tensor(np.asarray(source_faces, dtype=np.int64), dtype=torch.long, device=device)
    try:
        model = SMPLX(
            model_path=str(model_dir.expanduser().resolve()),
            gender=target_family,
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        ).to(device)
    except Exception as exc:
        raise SubjectAnatomyRefitV3Error(f"failed to load licensed SMPL-X {target_family} model: {exc}") from exc
    model.eval()

    faces_raw = getattr(model, "faces_tensor", None)
    if faces_raw is not None:
        donor_faces_tensor = faces_raw.to(device=device, dtype=torch.long)
        faces = [[int(item) for item in row] for row in faces_raw.detach().cpu().tolist()]
    else:
        raw = getattr(model, "faces", None)
        if raw is None:
            raise SubjectAnatomyRefitV3Error("target SMPL-X model exposes no faces")
        values = raw.tolist() if hasattr(raw, "tolist") else list(raw)
        faces = [[int(item) for item in row] for row in values]
        donor_faces_tensor = torch.tensor(np.asarray(faces, dtype=np.int64), dtype=torch.long, device=device)
    if not faces or any(len(face) != 3 for face in faces):
        raise SubjectAnatomyRefitV3Error("target SMPL-X topology is invalid")
    normal_sample_indices = _sample_face_indices(torch, face_count=len(faces), device=device)
    normal_sample_count = int(normal_sample_indices.shape[0])

    def fixed(field: str, width: int) -> Any:
        return torch.tensor(retained_params[field], dtype=torch.float32, device=device).view(1, width)

    retained_betas = fixed("betas", 10)
    base_transl = fixed("transl", 3)
    base_scale = float(retained_params["scale"][0])
    fixed_kwargs = {
        "expression": fixed("expression", 10),
        "global_orient": fixed("global_orient", 3),
        "body_pose": fixed("body_pose", 63),
        "left_hand_pose": fixed("left_hand_pose", 45),
        "right_hand_pose": fixed("right_hand_pose", 45),
        "jaw_pose": fixed("jaw_pose", 3),
        "leye_pose": fixed("leye_pose", 3),
        "reye_pose": fixed("reye_pose", 3),
        "return_verts": True,
    }

    def posed_for(betas: Any, transl: Any, scale: Any) -> Any:
        output = model(betas=betas, transl=transl, **fixed_kwargs)
        return output.vertices[0] * scale

    with torch.no_grad():
        base_scale_tensor = torch.tensor(base_scale, dtype=torch.float32, device=device)
        zero_betas = torch.zeros_like(retained_betas)
        zero_posed = posed_for(zero_betas, base_transl, base_scale_tensor)
        zero_indices = legacy._nearest_source_indices(torch, query=zero_posed, reference=source)
        zero_p95, zero_rms = legacy._distance_metrics(torch, zero_posed, source, zero_indices)
        zero_normal_mean, zero_normal_p05 = _surface_normal_metrics(
            torch,
            posed=zero_posed,
            donor_faces=donor_faces_tensor,
            sample_indices=normal_sample_indices,
            source=source,
            source_faces=source_faces_tensor,
            closest_point_fast=closest_point_fast,
            per_face_normals=per_face_normals,
        )

        retained_posed = posed_for(retained_betas, base_transl, base_scale_tensor)
        retained_indices = legacy._nearest_source_indices(torch, query=retained_posed, reference=source)
        retained_p95, retained_rms = legacy._distance_metrics(torch, retained_posed, source, retained_indices)
        retained_normal_mean, retained_normal_p05 = _surface_normal_metrics(
            torch,
            posed=retained_posed,
            donor_faces=donor_faces_tensor,
            sample_indices=normal_sample_indices,
            source=source,
            source_faces=source_faces_tensor,
            closest_point_fast=closest_point_fast,
            per_face_normals=per_face_normals,
        )

    zero_score = zero_rms + NORMAL_LOSS_WEIGHT * (1.0 - zero_normal_mean)
    retained_score = retained_rms + NORMAL_LOSS_WEIGHT * (1.0 - retained_normal_mean)
    if retained_score < zero_score:
        initial_betas = retained_betas.detach().clone()
        initial_p95, initial_rms = retained_p95, retained_rms
        initial_normal_mean, initial_normal_p05 = retained_normal_mean, retained_normal_p05
    else:
        initial_betas = zero_betas.detach().clone()
        initial_p95, initial_rms = zero_p95, zero_rms
        initial_normal_mean, initial_normal_p05 = zero_normal_mean, zero_normal_p05

    betas = torch.nn.Parameter(initial_betas)
    transl_delta = torch.nn.Parameter(torch.zeros((1, 3), dtype=torch.float32, device=device))
    log_scale_delta = torch.nn.Parameter(torch.zeros((), dtype=torch.float32, device=device))
    optimizer = torch.optim.Adam(
        [
            {"params": [betas], "lr": 0.025},
            {"params": [transl_delta], "lr": 0.003},
            {"params": [log_scale_delta], "lr": 0.002},
        ]
    )

    vertex_correspondence = None
    body_weights = None
    normal_target_normals = None
    normal_target_valid = None
    for step in range(ITERATIONS):
        optimizer.zero_grad(set_to_none=True)
        scale = base_scale * torch.exp(log_scale_delta)
        transl = base_transl + transl_delta
        posed = posed_for(betas, transl, scale)
        if vertex_correspondence is None or step % CORRESPONDENCE_INTERVAL == 0:
            vertex_correspondence = legacy._nearest_source_indices(torch, query=posed.detach(), reference=source)
            with torch.no_grad():
                y = posed.detach()[:, 1]
                height = torch.max(y) - torch.min(y)
                if not bool(torch.isfinite(height).item()) or float(height.item()) <= 1e-6:
                    raise SubjectAnatomyRefitV3Error("derived subject anatomy body height is invalid")
                yn = (y - torch.min(y)) / height
                body_weights = torch.ones_like(yn)
                body_weights = torch.where((yn >= 0.42) & (yn < 0.80), torch.full_like(yn, 2.0), body_weights)
                body_weights = torch.where((yn < 0.08) | (yn >= 0.80), torch.full_like(yn, 0.7), body_weights)
            normal_centroids, _normal_faces_now, _normal_valid_now = _sampled_surface(
                torch,
                vertices=posed,
                donor_faces=donor_faces_tensor,
                sample_indices=normal_sample_indices,
                per_face_normals=per_face_normals,
            )
            _normal_hit_points, normal_target_normals, normal_target_valid = _closest_source_surface(
                torch,
                query=normal_centroids,
                source=source,
                source_faces=source_faces_tensor,
                closest_point_fast=closest_point_fast,
                per_face_normals=per_face_normals,
            )

        assert vertex_correspondence is not None and body_weights is not None
        assert normal_target_normals is not None and normal_target_valid is not None
        target = source[vertex_correspondence]
        point_loss = F.smooth_l1_loss(posed, target, beta=0.02, reduction="none").sum(dim=1)
        data_loss = torch.sum(point_loss * body_weights) / torch.sum(body_weights)

        _centroids, donor_normal_faces, donor_normal_valid = _sampled_surface(
            torch,
            vertices=posed,
            donor_faces=donor_faces_tensor,
            sample_indices=normal_sample_indices,
            per_face_normals=per_face_normals,
        )
        valid = donor_normal_valid & normal_target_valid
        if int(valid.sum().item()) < MIN_NORMAL_FACE_COUNT:
            raise SubjectAnatomyRefitV3Error("too few valid normal correspondences during v3 optimization")
        alignment = torch.clamp(torch.sum(donor_normal_faces * normal_target_normals, dim=1), -1.0, 1.0)
        normal_loss = torch.mean(1.0 - alignment[valid])

        beta_reg = 0.0002 * torch.mean(betas * betas)
        transl_reg = 0.02 * torch.mean(transl_delta * transl_delta)
        scale_reg = 0.02 * log_scale_delta * log_scale_delta
        loss = data_loss + NORMAL_LOSS_WEIGHT * normal_loss + beta_reg + transl_reg + scale_reg
        if not bool(torch.isfinite(loss).item()):
            raise SubjectAnatomyRefitV3Error("subject anatomy v3 optimization became non-finite")
        loss.backward()
        optimizer.step()
        with torch.no_grad():
            betas.clamp_(-5.0, 5.0)
            transl_delta.clamp_(-0.10, 0.10)
            log_scale_delta.clamp_(-0.15, 0.15)

    with torch.no_grad():
        final_scale_tensor = base_scale * torch.exp(log_scale_delta)
        final_transl_tensor = base_transl + transl_delta
        final_posed = posed_for(betas, final_transl_tensor, final_scale_tensor)
        final_indices = legacy._nearest_source_indices(torch, query=final_posed, reference=source)
        final_p95, final_rms = legacy._distance_metrics(torch, final_posed, source, final_indices)
        final_normal_mean, final_normal_p05 = _surface_normal_metrics(
            torch,
            posed=final_posed,
            donor_faces=donor_faces_tensor,
            sample_indices=normal_sample_indices,
            source=source,
            source_faces=source_faces_tensor,
            closest_point_fast=closest_point_fast,
            per_face_normals=per_face_normals,
        )
        final_vertices = final_posed.detach().cpu().numpy()
        final_betas = [float(value) for value in betas.detach().cpu().reshape(-1).tolist()]
        final_transl = [float(value) for value in final_transl_tensor.detach().cpu().reshape(-1).tolist()]
        final_scale = float(final_scale_tensor.item())

    derived_params = legacy._fit_payload(
        retained_params,
        betas=final_betas,
        transl=final_transl,
        scale=final_scale,
    )
    receipt = build_receipt_v3(
        target_family=target_family,
        initial_p95=initial_p95,
        initial_rms=initial_rms,
        final_p95=final_p95,
        final_rms=final_rms,
        initial_normal_mean=initial_normal_mean,
        initial_normal_p05=initial_normal_p05,
        final_normal_mean=final_normal_mean,
        final_normal_p05=final_normal_p05,
        normal_sample_count=normal_sample_count,
        iterations=ITERATIONS,
    )
    receipt.update(retained_hashes)
    receipt["derivedScale"] = round(final_scale, 9)
    receipt["derivedBetas"] = [round(value, 9) for value in final_betas]
    receipt["derivedTransl"] = [round(value, 9) for value in final_transl]

    output_dir.mkdir(parents=True, exist_ok=False)
    derived_obj = output_dir / "subject_smplx.obj"
    derived_fit = output_dir / "subject_fit.json"
    evidence = output_dir / "subject-anatomy-refit.json"
    legacy._write_obj(derived_obj, vertices=final_vertices, faces=faces)
    derived_fit.write_text(json.dumps(derived_params, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    receipt["derivedSmplxObjSha256"] = legacy._sha256(derived_obj)
    receipt["derivedFitParamsSha256"] = legacy._sha256(derived_fit)
    evidence.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sith-repo", required=True)
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--bodyrig-workspace", required=True)
    parser.add_argument("--target-family", required=True, choices=TARGET_FAMILIES)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = refit_v3(
            sith_repo=Path(args.sith_repo),
            model_dir=Path(args.smplx_model_dir),
            workspace=Path(args.bodyrig_workspace),
            target_family=args.target_family,
            output_dir=Path(args.output_dir),
        )
        print(
            "BodyRig subject anatomy refit v3: PASS | "
            f"family={receipt['targetModelFamily']} | "
            f"method={receipt['method']} | "
            f"initial_p95={receipt['initialDonorToSourceP95']:.6f} | "
            f"final_p95={receipt['finalDonorToSourceP95']:.6f} | "
            f"initial_rms={receipt['initialDonorToSourceRms']:.6f} | "
            f"final_rms={receipt['finalDonorToSourceRms']:.6f} | "
            f"initial_normal_mean={receipt['initialNormalAlignmentMean']:.6f} | "
            f"final_normal_mean={receipt['finalNormalAlignmentMean']:.6f} | "
            f"initial_normal_p05={receipt['initialNormalAlignmentP05']:.6f} | "
            f"final_normal_p05={receipt['finalNormalAlignmentP05']:.6f} | "
            f"samples={receipt['normalSampleCount']} | "
            f"non_regression={receipt['fitDidNotRegress']}"
        )
        return 0
    except Exception as exc:
        print(f"BodyRig subject anatomy refit v3: FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
