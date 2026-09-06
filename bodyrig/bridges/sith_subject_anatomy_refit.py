from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping

import sith_smplx_vrm_fitter as base


FORMAT = "bodyrig-subject-anatomy-refit"
VERSION = 1
METHOD_V1 = "explicit-family-smplx-betas-icp-to-retained-sith-source-v1"
METHOD_V2 = "explicit-family-smplx-betas-icp-normal-aware-to-retained-sith-source-v2"
TARGET_FAMILIES = ("female", "male", "neutral")
ITERATIONS = 120
CORRESPONDENCE_INTERVAL = 10
# Real Lauren test-02 showed that the distance-only v1 optimizer could reduce
# donor-to-source distance while materially worsening the normal alignment used
# by the appearance bake. Keep the normal term modest relative to positional ICP,
# but make normal regression part of the comparison-only acceptance contract.
NORMAL_LOSS_WEIGHT = 0.04
NORMAL_NONREGRESSION_TOLERANCE = 1e-4
NORMAL_ALIGNMENT_AUTHORITY = "nearest-source-vertex-area-weighted-v1"
MIN_NORMAL_VERTEX_COUNT = 100


class SubjectAnatomyRefitError(ValueError):
    pass


def _sha256(path: Path) -> str:
    if not path.is_file():
        raise SubjectAnatomyRefitError(f"retained anatomy artifact is missing: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fit_payload(value: Mapping[str, Any], *, betas: list[float], transl: list[float], scale: float) -> dict[str, list[float]]:
    result = {key: [float(item) for item in raw] for key, raw in value.items()}
    if set(result) != set(base.FIT_PARAM_LENGTHS):
        raise SubjectAnatomyRefitError("retained fit parameter fields do not match BodyRig SiTH v1")
    if len(betas) != 10 or len(transl) != 3 or not math.isfinite(float(scale)) or float(scale) <= 0.0:
        raise SubjectAnatomyRefitError("derived anatomy fit parameters are invalid")
    if not all(math.isfinite(float(item)) for item in [*betas, *transl]):
        raise SubjectAnatomyRefitError("derived anatomy fit parameters are non-finite")
    result["betas"] = [float(item) for item in betas]
    result["transl"] = [float(item) for item in transl]
    result["scale"] = [float(scale)]
    return result


def build_receipt(
    *,
    target_family: str,
    initial_p95: float,
    initial_rms: float,
    final_p95: float,
    final_rms: float,
    iterations: int,
    initial_normal_mean: float | None = None,
    initial_normal_p05: float | None = None,
    final_normal_mean: float | None = None,
    final_normal_p05: float | None = None,
) -> dict[str, Any]:
    if target_family not in TARGET_FAMILIES:
        raise SubjectAnatomyRefitError("target SMPL-X model family is invalid")
    values = [float(initial_p95), float(initial_rms), float(final_p95), float(final_rms)]
    if any(not math.isfinite(value) or value < 0.0 for value in values):
        raise SubjectAnatomyRefitError("subject anatomy refit metrics are invalid")
    if isinstance(iterations, bool) or not isinstance(iterations, int) or iterations < 1:
        raise SubjectAnatomyRefitError("subject anatomy refit iteration count is invalid")

    distance_improved = final_rms <= initial_rms + 1e-9 and final_p95 <= initial_p95 + 1e-9
    normal_values = (initial_normal_mean, initial_normal_p05, final_normal_mean, final_normal_p05)
    normal_aware = any(value is not None for value in normal_values)
    if normal_aware and not all(value is not None for value in normal_values):
        raise SubjectAnatomyRefitError("normal-aware anatomy receipt requires all normal alignment metrics")

    method = METHOD_V1
    improved = distance_improved
    normal_fields: dict[str, Any] = {}
    if normal_aware:
        normalized = [float(value) for value in normal_values if value is not None]
        if len(normalized) != 4 or any(not math.isfinite(value) or not -1.0 <= value <= 1.0 for value in normalized):
            raise SubjectAnatomyRefitError("subject anatomy normal alignment metrics are invalid")
        initial_mean, initial_p05, final_mean, final_p05 = normalized
        normal_non_regression = (
            final_mean + NORMAL_NONREGRESSION_TOLERANCE >= initial_mean
            and final_p05 + NORMAL_NONREGRESSION_TOLERANCE >= initial_p05
        )
        method = METHOD_V2
        improved = distance_improved and normal_non_regression
        normal_fields = {
            "initialNormalAlignmentMean": round(initial_mean, 9),
            "initialNormalAlignmentP05": round(initial_p05, 9),
            "finalNormalAlignmentMean": round(final_mean, 9),
            "finalNormalAlignmentP05": round(final_p05, 9),
            "normalAwareNonRegression": bool(normal_non_regression),
            "normalAlignmentAuthority": NORMAL_ALIGNMENT_AUTHORITY,
            "normalLossWeight": NORMAL_LOSS_WEIGHT,
        }

    return {
        "format": FORMAT,
        "version": VERSION,
        "targetModelFamily": target_family,
        "method": method,
        "initialDonorToSourceP95": round(initial_p95, 9),
        "initialDonorToSourceRms": round(initial_rms, 9),
        "finalDonorToSourceP95": round(final_p95, 9),
        "finalDonorToSourceRms": round(final_rms, 9),
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
        **normal_fields,
    }


def _nearest_source_indices(torch: Any, *, query: Any, reference: Any) -> Any:
    count = int(query.shape[0])
    indices = torch.empty((count,), dtype=torch.long, device=query.device)
    query_chunk = 256
    reference_tile = 8192
    with torch.no_grad():
        for start in range(0, count, query_chunk):
            chunk = query[start:start + query_chunk]
            local_best = torch.full((int(chunk.shape[0]),), float("inf"), dtype=torch.float32, device=query.device)
            local_index = torch.full((int(chunk.shape[0]),), -1, dtype=torch.long, device=query.device)
            for ref_start in range(0, int(reference.shape[0]), reference_tile):
                ref = reference[ref_start:ref_start + reference_tile]
                distances = torch.cdist(chunk.unsqueeze(0), ref.unsqueeze(0)).squeeze(0)
                tile_best, tile_index = torch.min(distances, dim=1)
                improve = tile_best < local_best
                local_best = torch.where(improve, tile_best, local_best)
                local_index = torch.where(improve, tile_index + ref_start, local_index)
            if bool(torch.any(local_index < 0).item()):
                raise SubjectAnatomyRefitError("subject anatomy correspondence search was incomplete")
            indices[start:start + int(chunk.shape[0])] = local_index
    return indices


def _distance_metrics(torch: Any, posed: Any, source: Any, indices: Any) -> tuple[float, float]:
    target = source[indices]
    distances = torch.linalg.vector_norm(posed - target, dim=1)
    p95 = float(torch.quantile(distances, 0.95).item())
    rms = float(torch.sqrt(torch.mean(distances * distances)).item())
    if not math.isfinite(p95) or not math.isfinite(rms):
        raise SubjectAnatomyRefitError("subject anatomy distance metrics are non-finite")
    return p95, rms


def _vertex_normals(torch: Any, vertices: Any, faces: Any) -> tuple[Any, Any]:
    if vertices.ndim != 2 or int(vertices.shape[1]) != 3:
        raise SubjectAnatomyRefitError("normal-aware anatomy vertices are invalid")
    if faces.ndim != 2 or int(faces.shape[1]) != 3 or int(faces.shape[0]) < 1:
        raise SubjectAnatomyRefitError("normal-aware anatomy faces are invalid")
    a = vertices[faces[:, 0].long()]
    b = vertices[faces[:, 1].long()]
    c = vertices[faces[:, 2].long()]
    # Unnormalized cross products preserve triangle-area weighting when they are
    # accumulated into vertices, which is more stable on dense reconstructed
    # source meshes than giving tiny triangles the same vote as large triangles.
    face_area_normals = torch.cross(b - a, c - a, dim=1)
    accumulated = torch.zeros_like(vertices)
    for corner in range(3):
        accumulated = accumulated.index_add(0, faces[:, corner].long(), face_area_normals)
    lengths = torch.linalg.vector_norm(accumulated, dim=1, keepdim=True)
    valid = lengths[:, 0] > 1e-10
    unit = torch.where(
        valid[:, None],
        accumulated / torch.clamp(lengths, min=1e-10),
        torch.zeros_like(accumulated),
    )
    return unit, valid


def _normal_alignment_values(
    torch: Any,
    *,
    posed: Any,
    donor_faces: Any,
    source_normals: Any,
    source_normals_valid: Any,
    indices: Any,
) -> tuple[Any, Any]:
    donor_normals, donor_valid = _vertex_normals(torch, posed, donor_faces)
    target_normals = source_normals[indices]
    target_valid = source_normals_valid[indices]
    valid = donor_valid & target_valid
    if int(valid.sum().item()) < MIN_NORMAL_VERTEX_COUNT:
        raise SubjectAnatomyRefitError("too few valid vertices for normal-aware anatomy correspondence")
    alignment = torch.sum(donor_normals * target_normals, dim=1)
    alignment = torch.clamp(alignment, -1.0, 1.0)
    return alignment, valid


def _normal_metrics(
    torch: Any,
    *,
    posed: Any,
    donor_faces: Any,
    source_normals: Any,
    source_normals_valid: Any,
    indices: Any,
) -> tuple[float, float]:
    alignment, valid = _normal_alignment_values(
        torch,
        posed=posed,
        donor_faces=donor_faces,
        source_normals=source_normals,
        source_normals_valid=source_normals_valid,
        indices=indices,
    )
    values = alignment[valid]
    mean = float(torch.mean(values).item())
    p05 = float(torch.quantile(values, 0.05).item())
    if not math.isfinite(mean) or not math.isfinite(p05):
        raise SubjectAnatomyRefitError("subject anatomy normal alignment metrics are non-finite")
    return mean, p05


def _write_obj(path: Path, *, vertices: Any, faces: list[list[int]]) -> None:
    lines: list[str] = []
    for vertex in vertices:
        lines.append(f"v {float(vertex[0]):.9f} {float(vertex[1]):.9f} {float(vertex[2]):.9f}")
    for face in faces:
        if len(face) != 3:
            raise SubjectAnatomyRefitError("derived SMPL-X topology is not triangular")
        lines.append(f"f {int(face[0]) + 1} {int(face[1]) + 1} {int(face[2]) + 1}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def refit(
    *,
    model_dir: Path,
    workspace: Path,
    target_family: str,
    output_dir: Path,
) -> dict[str, Any]:
    if target_family not in TARGET_FAMILIES:
        raise SubjectAnatomyRefitError("target SMPL-X model family is invalid")
    if output_dir.exists():
        raise SubjectAnatomyRefitError(f"subject anatomy output already exists: {output_dir}")
    try:
        import numpy as np
        import torch
        import torch.nn.functional as F
        from smplx import SMPLX
    except ImportError as exc:
        raise SubjectAnatomyRefitError(f"subject anatomy refit dependencies are unavailable: {exc}") from exc
    if not torch.cuda.is_available():
        raise SubjectAnatomyRefitError("subject anatomy refit requires CUDA")

    stage = workspace / "sith-input-v1"
    reconstruction = stage / "reconstruction.json"
    smplx_obj = stage / "smplx" / "000_smplx.obj"
    fit_path = stage / "smplx" / "000_fit.json"
    source_path = stage / "meshes" / "000_reco.obj"
    retained_hashes = {
        "reconstructionSha256": _sha256(reconstruction),
        "retainedSmplxObjSha256": _sha256(smplx_obj),
        "retainedFitParamsSha256": _sha256(fit_path),
        "retainedSourceMeshSha256": _sha256(source_path),
    }

    retained_params = base._fit_params(fit_path)
    source_positions, _texcoords, source_faces_raw = base._parse_textured_obj(source_path)
    if len(source_positions) < 100:
        raise SubjectAnatomyRefitError("retained SiTH source mesh exposes too few vertices")
    source_faces = [[int(corner[0]) for corner in face] for face in source_faces_raw]
    if not source_faces or any(len(face) != 3 for face in source_faces):
        raise SubjectAnatomyRefitError("retained SiTH source mesh is not triangular")

    device = torch.device("cuda")
    source = torch.tensor(np.asarray(source_positions, dtype=np.float32), dtype=torch.float32, device=device)
    source_faces_tensor = torch.tensor(np.asarray(source_faces, dtype=np.int64), dtype=torch.long, device=device)
    try:
        model = SMPLX(
            model_path=str(model_dir),
            gender=target_family,
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        ).to(device)
    except Exception as exc:
        raise SubjectAnatomyRefitError(f"failed to load licensed SMPL-X {target_family} model: {exc}") from exc
    model.eval()

    faces_raw = getattr(model, "faces_tensor", None)
    if faces_raw is not None:
        donor_faces_tensor = faces_raw.to(device=device, dtype=torch.long)
        faces = [[int(item) for item in row] for row in faces_raw.detach().cpu().tolist()]
    else:
        raw = getattr(model, "faces", None)
        if raw is None:
            raise SubjectAnatomyRefitError("target SMPL-X model exposes no faces")
        values = raw.tolist() if hasattr(raw, "tolist") else list(raw)
        faces = [[int(item) for item in row] for row in values]
        donor_faces_tensor = torch.tensor(np.asarray(faces, dtype=np.int64), dtype=torch.long, device=device)
    if not faces or any(len(face) != 3 for face in faces):
        raise SubjectAnatomyRefitError("target SMPL-X topology is not triangular")

    with torch.no_grad():
        source_normals, source_normals_valid = _vertex_normals(torch, source, source_faces_tensor)

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
        zero_betas = torch.zeros_like(retained_betas)
        base_scale_tensor = torch.tensor(base_scale, dtype=torch.float32, device=device)
        zero_posed = posed_for(zero_betas, base_transl, base_scale_tensor)
        zero_indices = _nearest_source_indices(torch, query=zero_posed, reference=source)
        zero_p95, zero_rms = _distance_metrics(torch, zero_posed, source, zero_indices)
        zero_normal_mean, zero_normal_p05 = _normal_metrics(
            torch,
            posed=zero_posed,
            donor_faces=donor_faces_tensor,
            source_normals=source_normals,
            source_normals_valid=source_normals_valid,
            indices=zero_indices,
        )

        retained_posed = posed_for(retained_betas, base_transl, base_scale_tensor)
        retained_indices = _nearest_source_indices(torch, query=retained_posed, reference=source)
        retained_p95, retained_rms = _distance_metrics(torch, retained_posed, source, retained_indices)
        retained_normal_mean, retained_normal_p05 = _normal_metrics(
            torch,
            posed=retained_posed,
            donor_faces=donor_faces_tensor,
            source_normals=source_normals,
            source_normals_valid=source_normals_valid,
            indices=retained_indices,
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

    correspondence = None
    body_weights = None
    for step in range(ITERATIONS):
        optimizer.zero_grad(set_to_none=True)
        scale = base_scale * torch.exp(log_scale_delta)
        transl = base_transl + transl_delta
        posed = posed_for(betas, transl, scale)
        if correspondence is None or step % CORRESPONDENCE_INTERVAL == 0:
            correspondence = _nearest_source_indices(torch, query=posed.detach(), reference=source)
            with torch.no_grad():
                y = posed.detach()[:, 1]
                height = torch.max(y) - torch.min(y)
                if not bool(torch.isfinite(height).item()) or float(height.item()) <= 1e-6:
                    raise SubjectAnatomyRefitError("derived subject anatomy body height is invalid")
                yn = (y - torch.min(y)) / height
                body_weights = torch.ones_like(yn)
                body_weights = torch.where((yn >= 0.42) & (yn < 0.80), torch.full_like(yn, 2.0), body_weights)
                body_weights = torch.where((yn < 0.08) | (yn >= 0.80), torch.full_like(yn, 0.7), body_weights)
        assert correspondence is not None and body_weights is not None
        target = source[correspondence]
        point_loss = F.smooth_l1_loss(posed, target, beta=0.02, reduction="none").sum(dim=1)
        data_loss = torch.sum(point_loss * body_weights) / torch.sum(body_weights)

        alignment, normal_valid = _normal_alignment_values(
            torch,
            posed=posed,
            donor_faces=donor_faces_tensor,
            source_normals=source_normals,
            source_normals_valid=source_normals_valid,
            indices=correspondence,
        )
        normal_penalty = 1.0 - alignment[normal_valid]
        normal_weights = body_weights[normal_valid]
        normal_loss = torch.sum(normal_penalty * normal_weights) / torch.sum(normal_weights)

        beta_reg = 0.0002 * torch.mean(betas * betas)
        transl_reg = 0.02 * torch.mean(transl_delta * transl_delta)
        scale_reg = 0.02 * log_scale_delta * log_scale_delta
        loss = data_loss + NORMAL_LOSS_WEIGHT * normal_loss + beta_reg + transl_reg + scale_reg
        if not bool(torch.isfinite(loss).item()):
            raise SubjectAnatomyRefitError("subject anatomy optimization became non-finite")
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
        final_indices = _nearest_source_indices(torch, query=final_posed, reference=source)
        final_p95, final_rms = _distance_metrics(torch, final_posed, source, final_indices)
        final_normal_mean, final_normal_p05 = _normal_metrics(
            torch,
            posed=final_posed,
            donor_faces=donor_faces_tensor,
            source_normals=source_normals,
            source_normals_valid=source_normals_valid,
            indices=final_indices,
        )
        final_vertices = final_posed.detach().cpu().numpy()
        final_betas = [float(value) for value in betas.detach().cpu().reshape(-1).tolist()]
        final_transl = [float(value) for value in final_transl_tensor.detach().cpu().reshape(-1).tolist()]
        final_scale = float(final_scale_tensor.item())

    derived_params = _fit_payload(
        retained_params,
        betas=final_betas,
        transl=final_transl,
        scale=final_scale,
    )
    receipt = build_receipt(
        target_family=target_family,
        initial_p95=initial_p95,
        initial_rms=initial_rms,
        final_p95=final_p95,
        final_rms=final_rms,
        iterations=ITERATIONS,
        initial_normal_mean=initial_normal_mean,
        initial_normal_p05=initial_normal_p05,
        final_normal_mean=final_normal_mean,
        final_normal_p05=final_normal_p05,
    )
    receipt.update(retained_hashes)
    receipt["derivedScale"] = round(final_scale, 9)
    receipt["derivedBetas"] = [round(value, 9) for value in final_betas]
    receipt["derivedTransl"] = [round(value, 9) for value in final_transl]

    output_dir.mkdir(parents=True, exist_ok=False)
    derived_obj = output_dir / "subject_smplx.obj"
    derived_fit = output_dir / "subject_fit.json"
    evidence = output_dir / "subject-anatomy-refit.json"
    _write_obj(derived_obj, vertices=final_vertices, faces=faces)
    derived_fit.write_text(json.dumps(derived_params, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    receipt["derivedSmplxObjSha256"] = _sha256(derived_obj)
    receipt["derivedFitParamsSha256"] = _sha256(derived_fit)
    evidence.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--bodyrig-workspace", required=True)
    parser.add_argument("--target-family", required=True, choices=TARGET_FAMILIES)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = refit(
            model_dir=Path(args.smplx_model_dir).expanduser().resolve(),
            workspace=Path(args.bodyrig_workspace).expanduser().resolve(),
            target_family=args.target_family,
            output_dir=Path(args.output_dir).expanduser().resolve(),
        )
        print(
            "BodyRig subject anatomy refit: PASS | "
            f"family={receipt['targetModelFamily']} | "
            f"method={receipt['method']} | "
            f"initial_p95={receipt['initialDonorToSourceP95']:.6f} | "
            f"final_p95={receipt['finalDonorToSourceP95']:.6f} | "
            f"initial_rms={receipt['initialDonorToSourceRms']:.6f} | "
            f"final_rms={receipt['finalDonorToSourceRms']:.6f} | "
            f"initial_normal_mean={receipt.get('initialNormalAlignmentMean', 1.0):.6f} | "
            f"final_normal_mean={receipt.get('finalNormalAlignmentMean', 1.0):.6f} | "
            f"initial_normal_p05={receipt.get('initialNormalAlignmentP05', 1.0):.6f} | "
            f"final_normal_p05={receipt.get('finalNormalAlignmentP05', 1.0):.6f} | "
            f"non_regression={receipt['fitDidNotRegress']}"
        )
        return 0
    except Exception as exc:
        print(f"BodyRig subject anatomy refit: FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
