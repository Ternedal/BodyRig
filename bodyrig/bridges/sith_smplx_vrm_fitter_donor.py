#!/usr/bin/env python
"""BodyRig donor-topology fitter: stable fitted SMPL-X geometry + SiTH appearance.

The historical bridge used the reconstructed SiTH shell as final render geometry
and transferred only SMPL-X rigging onto it. Physical runs showed that this can
preserve reconstruction membranes, holes and high-frequency geometric noise.

This fitter reverses that authority boundary:
* fitted SMPL-X owns vertices, faces and LBS weights;
* SiTH remains source-derived appearance authority through its exact texture;
* each SMPL-X donor vertex is mapped to its exact nearest textured SiTH source
  vertex that belongs to at least one geometrically usable source face;
* donor face corners then receive local-triangle barycentric UVs so source atlas
  seams are not collapsed to one canonical UV per source vertex;
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
from sith_donor_topology import DonorTopologyError, canonical_source_uv_map
from sith_donor_vrm_metadata import DonorVrmMetadataError, mark_donor_topology
from sith_surface_uv_transfer import SurfaceUvTransferError, build_surface_projected_donor_uvs

_CURRENT_ADJUSTMENT: dict[str, Any] | None = None
_SOURCE_FACE_AREA_EPSILON = 1e-12


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


def _usable_textured_source_vertices(
    *,
    source_positions: Any,
    source_faces: Any,
    source_uv_map: dict[int, int],
) -> set[int]:
    """Return textured source vertices incident to a non-degenerate geometric face.

    A UV-bearing vertex is not a valid appearance seed when every incident face
    has zero geometric area. Selecting such a vertex caused the physical #41
    fit-only A/B to fail only after donor mapping. Filter it before nearest-seed
    selection instead; geometry, topology, skinning and source texture bytes are
    unchanged.
    """

    usable: set[int] = set()
    source_count = len(source_positions)
    for raw_face in source_faces:
        if len(raw_face) != 3:
            raise base.FitterError("SiTH source UV topology must be triangular")
        vertices = [int(corner[0]) for corner in raw_face]
        if any(vertex < 0 or vertex >= source_count for vertex in vertices):
            raise base.FitterError("SiTH source UV face index is outside range")
        if len(set(vertices)) != 3:
            continue

        a = source_positions[vertices[0]]
        b = source_positions[vertices[1]]
        c = source_positions[vertices[2]]
        ab = (float(b[0]) - float(a[0]), float(b[1]) - float(a[1]), float(b[2]) - float(a[2]))
        ac = (float(c[0]) - float(a[0]), float(c[1]) - float(a[1]), float(c[2]) - float(a[2]))
        cross = (
            ab[1] * ac[2] - ab[2] * ac[1],
            ab[2] * ac[0] - ab[0] * ac[2],
            ab[0] * ac[1] - ab[1] * ac[0],
        )
        area_sq = cross[0] * cross[0] + cross[1] * cross[1] + cross[2] * cross[2]
        if not math.isfinite(area_sq):
            raise base.FitterError("SiTH source UV face geometry is non-finite")
        if area_sq <= _SOURCE_FACE_AREA_EPSILON:
            continue
        usable.update(vertex for vertex in vertices if vertex in source_uv_map)

    if len(usable) < 3:
        raise base.FitterError("SiTH source mesh exposes too few textured vertices on non-degenerate faces")
    return usable


def _map_donor_vertices_to_textured_source(
    *,
    torch: Any,
    donor_posed: Any,
    source_posed: Any,
    source_uv_map: dict[int, int],
    usable_source_vertices: set[int],
    device: Any,
) -> tuple[list[int], list[float]]:
    """Find the exact nearest usable textured source vertex for every donor vertex.

    The search is tiled so the full donor-by-source distance matrix is never held
    in VRAM. Ties remain deterministic because source indices are sorted and later
    tiles replace an earlier match only when the distance is strictly smaller.
    """

    valid_source = sorted(vertex for vertex in source_uv_map if vertex in usable_source_vertices)
    if len(valid_source) < 3:
        raise base.FitterError("SiTH source mesh exposes too few usable textured vertices")
    valid_index = torch.tensor(valid_source, dtype=torch.long, device=device)
    textured_source = source_posed[valid_index]

    donor_count = int(donor_posed.shape[0])
    if donor_count < 3:
        raise base.FitterError("SMPL-X donor mesh exposes too few vertices")
    best_source = [-1] * donor_count
    best_distance = [float("inf")] * donor_count

    donor_chunk = 256
    source_tile = 8192
    for donor_start in range(0, donor_count, donor_chunk):
        donor_tensor = donor_posed[donor_start:donor_start + donor_chunk]
        local_count = int(donor_tensor.shape[0])
        local_best = torch.full((local_count,), float("inf"), dtype=torch.float32, device=device)
        local_source = torch.full((local_count,), -1, dtype=torch.long, device=device)

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
        for offset, (source_vertex, distance) in enumerate(zip(resolved_source, resolved_distance)):
            donor_vertex = donor_start + offset
            if int(source_vertex) < 0 or not math.isfinite(float(distance)):
                raise base.FitterError("donor appearance mapping could not resolve a usable textured source vertex")
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
            raise base.FitterError(f"SiTH donor appearance UV seed mapping failed: {exc}") from exc

        usable_source_vertices = _usable_textured_source_vertices(
            source_positions=source_positions,
            source_faces=source_faces,
            source_uv_map=source_uv_map,
        )
        source_tensor = torch.tensor(source_obj, dtype=torch.float32, device=device)
        donor_to_source, source_distances = _map_donor_vertices_to_textured_source(
            torch=torch,
            donor_posed=posed_donor,
            source_posed=source_tensor,
            source_uv_map=source_uv_map,
            usable_source_vertices=usable_source_vertices,
            device=device,
        )
        donor_faces_raw = _donor_faces(model)
        try:
            projected_texcoords, faces, projection_metrics = build_surface_projected_donor_uvs(
                donor_faces=donor_faces_raw,
                donor_positions=posed_donor.detach().cpu().tolist(),
                source_positions=source_positions,
                source_faces=source_faces,
                source_texcoords=texcoords,
                donor_to_source_vertex=donor_to_source,
            )
        except SurfaceUvTransferError as exc:
            raise base.FitterError(f"SiTH donor barycentric UV projection failed: {exc}") from exc

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
    projection_p95 = float(projection_metrics["projection_distance_p95"])
    projection_max = float(projection_metrics["projection_distance_max"])
    if not all(math.isfinite(value) for value in (source_p95, source_max, projection_p95, projection_max)):
        raise base.FitterError("SMPL-X donor appearance mapping distance is non-finite")
    if source_p95 > 0.30 or source_max > 0.85:
        raise base.FitterError(
            f"SiTH source appearance is too far from fitted SMPL-X donor surface (p95={source_p95:.4f}, max={source_max:.4f})"
        )
    if projection_max > source_max + 0.002:
        raise base.FitterError(
            "SiTH barycentric UV projection escaped its nearest-source locality "
            f"(projection_max={projection_max:.6f}, seed_max={source_max:.6f})"
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
        "uv_projection_distance_p95": projection_p95,
        "uv_projection_distance_max": projection_max,
        "uv_seam_seed_corner_ratio": float(projection_metrics["seam_seed_corner_ratio"]),
        "usable_source_seed_vertex_count": float(len(usable_source_vertices)),
        "filtered_source_seed_vertex_count": float(len(source_uv_map) - len(usable_source_vertices)),
    }
    texture = paths["texture"].read_bytes()
    avatar, thumbnail = base._build_vrm(
        np=np,
        name=name,
        rest_positions=rest_positions,
        texcoords=projected_texcoords,
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
                "projection_distance_p95": projection_p95,
                "projection_distance_max": projection_max,
                "seam_seed_corner_ratio": float(projection_metrics["seam_seed_corner_ratio"]),
                "projected_corner_count": float(projection_metrics["projected_corner_count"]),
                "degenerate_source_candidate_count": float(projection_metrics["degenerate_source_candidate_count"]),
                "maximum_local_source_face_candidates": float(projection_metrics["maximum_local_source_face_candidates"]),
            },
        )
    except DonorVrmMetadataError as exc:
        raise base.FitterError(f"SMPL-X donor metadata binding failed: {exc}") from exc

    print(
        "BodyRig SMPL-X donor topology: "
        f"vertices={len(rest_positions)} faces={len(faces)} "
        f"fit_max={fit_max:.6f} fit_rms={fit_rms:.6f} "
        f"source_seed_p95={source_p95:.6f} source_seed_max={source_max:.6f} "
        f"usable_source_seeds={len(usable_source_vertices)} "
        f"filtered_source_seeds={len(source_uv_map) - len(usable_source_vertices)} "
        f"uv_projection_p95={projection_p95:.6f} uv_projection_max={projection_max:.6f} "
        f"seam_seed_ratio={float(projection_metrics['seam_seed_corner_ratio']):.6f}",
        file=sys.stderr,
    )
    return avatar, thumbnail, quality


base._validate_request = _validate_request
base._rig_mesh = _rig_mesh

if __name__ == "__main__":
    raise SystemExit(base.main())