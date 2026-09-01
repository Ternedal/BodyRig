#!/usr/bin/env python
"""BodyRig donor-topology fitter: stable fitted SMPL-X geometry + SiTH appearance.

The historical bridge used the reconstructed SiTH shell as final render geometry
and transferred only SMPL-X rigging onto it. Physical runs showed that this can
preserve reconstruction membranes, holes and high-frequency geometric noise.

This fitter reverses that authority boundary:
* fitted SMPL-X owns vertices, faces and LBS weights;
* SiTH remains source-derived appearance authority through its exact texture;
* each SMPL-X donor vertex is mapped to a textured SiTH source vertex for UV;
* BodyPrint adjustments remain bounded and operate on the stable donor mesh;
* no source-reconstruction vertex is serialized as final body geometry.
"""
from __future__ import annotations

import math
import sys
from typing import Any

import sith_smplx_vrm_fitter as base
from bodyprint_shape_adjust import (
    BodyprintAdjustmentError,
    apply_shape_adjustment,
    validate_adjustment_payload,
)
from sith_anatomy_guard import (
    ANATOMY_GUARD_THRESHOLD,
    LIMB_REGIONS,
    classify_strong_limb_regions,
    forbidden_joint_indices,
)
from sith_donor_topology import (
    DonorTopologyError,
    build_donor_faces,
    canonical_source_uv_map,
)
from sith_donor_vrm_metadata import DonorVrmMetadataError, mark_donor_topology

_CURRENT_ADJUSTMENT: dict[str, Any] | None = None


def _validate_request(path: Any, adapter: str, revision: str) -> dict[str, Any]:
    global _CURRENT_ADJUSTMENT
    request = base._read_json(path, label="BodyRig fitter request")
    required = {"format", "version", "name", "bodyprint", "visual_identity"}
    allowed = required | {"bodyprint_adjustment"}
    if not required <= set(request) or set(request) - allowed:
        raise base.FitterError("BodyRig fitter request fields do not match v1")
    if request["format"] != base.REQUEST_FORMAT or request["version"] != 1:
        raise base.FitterError("unsupported BodyRig fitter request")
    if adapter != base.ADAPTER or revision != base.REVISION:
        raise base.FitterError("BodyRig fitter adapter/revision mismatch")
    name = request["name"]
    if not isinstance(name, str) or not name.strip() or len(name) > 160:
        raise base.FitterError("BodyRig avatar name is invalid")
    identity = request["visual_identity"]
    if not isinstance(identity, dict):
        raise base.FitterError("BodyRig visual identity is missing")
    if identity.get("format") != "bodyrig-visual-identity" or identity.get("version") != 1:
        raise base.FitterError("unsupported BodyRig visual identity")
    track = identity.get("subject_track_id")
    if not isinstance(track, str) or not track or len(track) > 160:
        raise base.FitterError("BodyRig visual identity track id is invalid")
    privacy = identity.get("privacy")
    if privacy != {"contains_source_media": False, "contains_biometric_template": False}:
        raise base.FitterError("BodyRig visual identity privacy boundary is invalid")

    raw_adjustment = request.get("bodyprint_adjustment")
    if raw_adjustment is None:
        _CURRENT_ADJUSTMENT = None
    else:
        try:
            _CURRENT_ADJUSTMENT = validate_adjustment_payload(raw_adjustment)
        except BodyprintAdjustmentError as exc:
            raise base.FitterError(f"BodyPrint adjustment is invalid: {exc}") from exc
    return request


def _donor_faces(model: Any) -> list[list[int]]:
    raw = getattr(model, "faces_tensor", None)
    if raw is not None:
        values = raw.detach().cpu().tolist()
    else:
        raw = getattr(model, "faces", None)
        if raw is None:
            raise base.FitterError("SMPL-X model does not expose donor faces")
        values = raw.tolist() if hasattr(raw, "tolist") else list(raw)
    result = [[int(value) for value in face] for face in values]
    if not result or any(len(face) != 3 for face in result):
        raise base.FitterError("SMPL-X donor topology is not triangular")
    return result


def _map_donor_vertices_to_textured_source(
    *,
    torch: Any,
    donor_posed: Any,
    source_posed: Any,
    source_uv_map: dict[int, int],
    device: Any,
) -> tuple[list[int], list[float]]:
    """Map every donor vertex to a textured source vertex with bounded GPU memory."""

    valid_source = sorted(source_uv_map)
    if len(valid_source) < 3:
        raise base.FitterError("SiTH source mesh exposes too few textured vertices")
    valid_index = torch.tensor(valid_source, dtype=torch.long, device=device)
    textured_source = source_posed[valid_index]

    donor_count = int(donor_posed.shape[0])
    best_source = [-1] * donor_count
    best_distance = [float("inf")] * donor_count

    # Source -> nearest donor is memory efficient and normally assigns appearance
    # evidence to every exposed donor surface vertex. Keep only the closest source
    # sample per donor vertex.
    source_chunk = 768
    for start in range(0, int(textured_source.shape[0]), source_chunk):
        chunk = textured_source[start:start + source_chunk]
        distances = torch.cdist(chunk.unsqueeze(0), donor_posed.unsqueeze(0)).squeeze(0)
        nearest_distance, nearest_donor = torch.min(distances, dim=1)
        source_indices = valid_index[start:start + len(chunk)].detach().cpu().tolist()
        donor_indices = nearest_donor.detach().cpu().tolist()
        distance_values = nearest_distance.detach().cpu().tolist()
        for source_vertex, donor_vertex, distance in zip(source_indices, donor_indices, distance_values):
            donor_vertex = int(donor_vertex)
            distance = float(distance)
            if distance < best_distance[donor_vertex]:
                best_distance[donor_vertex] = distance
                best_source[donor_vertex] = int(source_vertex)

    missing = [index for index, source_vertex in enumerate(best_source) if source_vertex < 0]
    if missing:
        # Closed/internal or sparsely sampled donor areas may receive no source in
        # the inverse assignment. Resolve only those vertices with a tiled exact
        # nearest-source search to avoid a donor_count x source_count allocation.
        donor_chunk = 96
        source_tile = 4096
        for missing_start in range(0, len(missing), donor_chunk):
            donor_ids = missing[missing_start:missing_start + donor_chunk]
            donor_tensor = donor_posed[torch.tensor(donor_ids, dtype=torch.long, device=device)]
            local_best = torch.full((len(donor_ids),), float("inf"), dtype=torch.float32, device=device)
            local_source = torch.full((len(donor_ids),), -1, dtype=torch.long, device=device)
            for source_start in range(0, int(textured_source.shape[0]), source_tile):
                source = textured_source[source_start:source_start + source_tile]
                distances = torch.cdist(donor_tensor.unsqueeze(0), source.unsqueeze(0)).squeeze(0)
                tile_distance, tile_local = torch.min(distances, dim=1)
                improve = tile_distance < local_best
                if bool(torch.any(improve).item()):
                    local_best = torch.where(improve, tile_distance, local_best)
                    source_global = valid_index[source_start + tile_local]
                    local_source = torch.where(improve, source_global, local_source)
            resolved_source = local_source.detach().cpu().tolist()
            resolved_distance = local_best.detach().cpu().tolist()
            for donor_vertex, source_vertex, distance in zip(donor_ids, resolved_source, resolved_distance):
                if int(source_vertex) < 0 or not math.isfinite(float(distance)):
                    raise base.FitterError("donor appearance mapping could not resolve a textured source vertex")
                best_source[donor_vertex] = int(source_vertex)
                best_distance[donor_vertex] = float(distance)

    if any(source_vertex < 0 for source_vertex in best_source) or any(not math.isfinite(value) for value in best_distance):
        raise base.FitterError("donor appearance mapping is incomplete or non-finite")
    return best_source, best_distance


def _rig_mesh(paths: dict[str, Any], *, model_dir: str, name: str) -> tuple[bytes, bytes, dict[str, float]]:
    try:
        import numpy as np
        import torch
        from smplx import SMPLX
        from smplx.lbs import blend_shapes, vertices2joints
    except ImportError as exc:
        raise base.FitterError("numpy, torch and smplx are required in the SiTH fitter environment") from exc
    if not torch.cuda.is_available():
        raise base.FitterError("SiTH SMPL-X VRM fitting requires CUDA")

    device = torch.device("cuda")
    params = base._fit_params(paths["fit_params"])
    donor_obj = np.asarray(base._parse_positions(paths["smplx_obj"]), dtype=np.float32)
    source_positions, texcoords, source_faces = base._parse_textured_obj(paths["mesh_obj"])
    source_obj = np.asarray(source_positions, dtype=np.float32)

    try:
        model = SMPLX(
            model_path=model_dir,
            gender="male",
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        ).to(device)
    except Exception as exc:
        raise base.FitterError("failed to load the licensed SMPL-X male model") from exc
    model.eval()
    if int(model.lbs_weights.shape[0]) != len(donor_obj) or int(model.lbs_weights.shape[1]) != len(base.SMPLX_JOINT_NAMES):
        raise base.FitterError("SMPL-X model topology does not match SiTH fitted OBJ")
    parents = [int(value) for value in model.parents.detach().cpu().tolist()]
    if len(parents) != len(base.SMPLX_JOINT_NAMES) or parents[0] != -1:
        raise base.FitterError("SMPL-X parent topology is incompatible with BodyRig v1")

    def tensor(field: str, width: int) -> Any:
        return torch.tensor(params[field], dtype=torch.float32, device=device).view(1, width)

    betas = tensor("betas", 10)
    expression = tensor("expression", 10)
    global_orient = tensor("global_orient", 3)
    body_pose = tensor("body_pose", 63)
    left_hand = tensor("left_hand_pose", 45)
    right_hand = tensor("right_hand_pose", 45)
    jaw = tensor("jaw_pose", 3)
    leye = tensor("leye_pose", 3)
    reye = tensor("reye_pose", 3)
    transl = tensor("transl", 3)
    scale = float(params["scale"][0])

    with torch.no_grad():
        output = model(
            betas=betas,
            expression=expression,
            global_orient=global_orient,
            body_pose=body_pose,
            left_hand_pose=left_hand,
            right_hand_pose=right_hand,
            jaw_pose=jaw,
            leye_pose=leye,
            reye_pose=reye,
            transl=transl,
            return_verts=True,
        )
        posed_donor = output.vertices[0] * scale
        donor_tensor = torch.tensor(donor_obj, dtype=torch.float32, device=device)
        fit_delta = torch.linalg.vector_norm(posed_donor - donor_tensor, dim=1)
        fit_max = float(fit_delta.max().item())
        fit_rms = float(torch.sqrt(torch.mean(fit_delta * fit_delta)).item())
        if fit_max > 0.005 or fit_rms > 0.001:
            raise base.FitterError("SiTH fit parameters do not numerically reproduce the fitted SMPL-X OBJ")

        shape_components = torch.cat([betas, expression], dim=-1)
        shapedirs = torch.cat([model.shapedirs, model.expr_dirs], dim=-1)
        v_shaped = model.v_template + blend_shapes(shape_components, shapedirs)
        rest_joints = vertices2joints(model.J_regressor, v_shaped)
        rest_positions = v_shaped[0].detach().cpu().numpy().astype(np.float32, copy=True)
        final_joints = rest_joints[0].detach().cpu().numpy().astype(np.float32, copy=True)

        full_weights = model.lbs_weights
        top_weight, top_joint = torch.topk(full_weights, k=4, dim=1)
        totals = top_weight.sum(dim=1, keepdim=True)
        if bool(torch.any(totals <= 1e-8).item()):
            raise base.FitterError("SMPL-X donor skin weights contain an empty influence set")
        top_weight = top_weight / totals
        joints4 = top_joint.detach().cpu().numpy()
        weights4 = top_weight.detach().cpu().numpy()

        try:
            source_uv_map, uv_metrics = canonical_source_uv_map(
                source_vertex_count=len(source_obj),
                texcoord_count=len(texcoords),
                faces=source_faces,
            )
        except DonorTopologyError as exc:
            raise base.FitterError(f"SiTH donor appearance UV mapping failed: {exc}") from exc

        source_tensor = torch.tensor(source_obj, dtype=torch.float32, device=device)
        donor_to_source, source_distances = _map_donor_vertices_to_textured_source(
            torch=torch,
            donor_posed=posed_donor,
            source_posed=source_tensor,
            source_uv_map=source_uv_map,
            device=device,
        )
        donor_faces_raw = _donor_faces(model)
        try:
            faces = build_donor_faces(
                donor_faces=donor_faces_raw,
                donor_vertex_count=len(rest_positions),
                donor_to_source_vertex=donor_to_source,
                source_uv_map=source_uv_map,
            )
        except DonorTopologyError as exc:
            raise base.FitterError(f"SMPL-X donor topology binding failed: {exc}") from exc

        adjustment_metrics: dict[str, float] = {"max_joint_delta": 0.0}
        if _CURRENT_ADJUSTMENT is not None:
            try:
                rest_positions, final_joints, adjustment_metrics = apply_shape_adjustment(
                    np=np,
                    rest_positions=rest_positions,
                    rest_joints=final_joints,
                    joints4=joints4,
                    weights4=weights4,
                    joint_names=base.SMPLX_JOINT_NAMES,
                    adjustment=_CURRENT_ADJUSTMENT,
                )
            except BodyprintAdjustmentError as exc:
                raise base.FitterError(f"BodyPrint shape adjustment failed: {exc}") from exc

        # Direct donor weights should never contain opposite-limb transfer. Keep
        # the same strong-region semantics as production skin QA and fail closed.
        try:
            regions, _body_scale = classify_strong_limb_regions(
                rest_positions.tolist(),
                final_joints.tolist(),
                parents,
                base.SMPLX_JOINT_NAMES,
            )
        except ValueError as exc:
            raise base.FitterError(f"SMPL-X donor anatomy classification failed: {exc}") from exc
        forbidden_by_region = {
            region: set(forbidden_joint_indices(base.SMPLX_JOINT_NAMES, region))
            for region in LIMB_REGIONS
        }
        violations: list[tuple[int, str, float]] = []
        for vertex, region in enumerate(regions):
            if region is None:
                continue
            forbidden = forbidden_by_region[region]
            mass = sum(
                float(weight)
                for joint, weight in zip(joints4[vertex], weights4[vertex])
                if int(joint) in forbidden
            )
            if mass > ANATOMY_GUARD_THRESHOLD + 1e-6:
                violations.append((vertex, region, mass))
        if violations:
            worst = max(violations, key=lambda item: item[2])
            raise base.FitterError(
                "SMPL-X donor direct-LBS anatomy validation failed "
                f"(violations={len(violations)}, vertex={worst[0]}, region={worst[1]}, forbidden_weight={worst[2]:.6f})"
            )

    source_distance_array = np.asarray(source_distances, dtype=np.float32)
    source_p95 = float(np.quantile(source_distance_array, 0.95))
    source_max = float(np.max(source_distance_array))
    if not math.isfinite(source_p95) or not math.isfinite(source_max):
        raise base.FitterError("SMPL-X donor appearance mapping distance is non-finite")
    if source_p95 > 0.30 or source_max > 0.85:
        raise base.FitterError(
            f"SiTH source appearance is too far from fitted SMPL-X donor surface (p95={source_p95:.4f}, max={source_max:.4f})"
        )

    quality = {
        "nearest_p95": 0.0,
        "nearest_max": 0.0,
        "adjustment_max_joint_delta": float(adjustment_metrics.get("max_joint_delta", 0.0)),
        "donor_vertex_count": float(len(rest_positions)),
        "donor_face_count": float(len(faces)),
        "source_surface_distance_p95": source_p95,
        "source_surface_distance_max": source_max,
        "source_multi_uv_vertex_ratio": float(uv_metrics["multi_uv_source_vertex_ratio"]),
    }
    texture = paths["texture"].read_bytes()
    avatar, thumbnail = base._build_vrm(
        np=np,
        name=name,
        rest_positions=rest_positions,
        texcoords=texcoords,
        faces=faces,
        joints4=joints4,
        weights4=weights4,
        rest_joints=final_joints,
        parents=parents,
        texture_png=texture,
        quality=quality,
    )
    try:
        avatar = mark_donor_topology(
            avatar,
            mapping_metrics={
                "source_surface_distance_p95": source_p95,
                "source_surface_distance_max": source_max,
                "multi_uv_source_vertex_ratio": float(uv_metrics["multi_uv_source_vertex_ratio"]),
            },
        )
    except DonorVrmMetadataError as exc:
        raise base.FitterError(f"SMPL-X donor metadata binding failed: {exc}") from exc

    print(
        "BodyRig SMPL-X donor topology: "
        f"vertices={len(rest_positions)} faces={len(faces)} "
        f"fit_max={fit_max:.6f} fit_rms={fit_rms:.6f} "
        f"source_uv_p95={source_p95:.6f} source_uv_max={source_max:.6f} "
        f"multi_uv_ratio={float(uv_metrics['multi_uv_source_vertex_ratio']):.6f}",
        file=sys.stderr,
    )
    return avatar, thumbnail, quality


base._validate_request = _validate_request
base._rig_mesh = _rig_mesh

if __name__ == "__main__":
    raise SystemExit(base.main())
