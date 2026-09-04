#!/usr/bin/env python
"""BodyRig SiTH fitter entrypoint with bounded reviewed BodyPrint adjustments.

This is a thin one-shot wrapper around sith_smplx_vrm_fitter.py. The original
standalone bridge remains the source-derived fitter authority; this wrapper only
adds optional, bounded rest-pose proportion deltas before the existing VRM
builder serializes the mesh.
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
    MAX_GUARD_DISTANCE_RATIO,
    MAX_GUARD_DISTANCE_SCALE,
    MAX_GUARD_EXTRA_SCALE,
    classify_strong_limb_regions,
    forbidden_joint_indices,
)

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


def _rig_mesh(paths: dict[str, Any], *, model_dir: str, name: str) -> tuple[bytes, bytes, dict[str, float]]:
    try:
        import numpy as np
        import torch
        from smplx import SMPLX
        from smplx.lbs import batch_rigid_transform, batch_rodrigues, blend_shapes, vertices2joints
    except ImportError as exc:
        raise base.FitterError("numpy, torch and smplx are required in the SiTH fitter environment") from exc
    if not torch.cuda.is_available():
        raise base.FitterError("SiTH SMPL-X VRM fitting requires CUDA")

    device = torch.device("cuda")
    params = base._fit_params(paths["fit_params"])
    donor_obj = np.asarray(base._parse_positions(paths["smplx_obj"]), dtype=np.float32)
    reco_positions_list, texcoords, faces = base._parse_textured_obj(paths["mesh_obj"])
    reco_obj = np.asarray(reco_positions_list, dtype=np.float32)

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
        posed_model = output.vertices[0] * scale
        donor_tensor = torch.tensor(donor_obj, dtype=torch.float32, device=device)
        delta = torch.linalg.vector_norm(posed_model - donor_tensor, dim=1)
        if float(delta.max().item()) > 0.005 or float(torch.sqrt(torch.mean(delta * delta)).item()) > 0.001:
            raise base.FitterError("SiTH fit parameters do not numerically reproduce the fitted SMPL-X OBJ")

        shape_components = torch.cat([betas, expression], dim=-1)
        shapedirs = torch.cat([model.shapedirs, model.expr_dirs], dim=-1)
        v_shaped = model.v_template + blend_shapes(shape_components, shapedirs)
        rest_joints = vertices2joints(model.J_regressor, v_shaped)
        rest_joints_np = rest_joints[0].detach().cpu().numpy()

        full_pose = torch.cat([
            global_orient.view(1, 1, 3),
            body_pose.view(1, 21, 3),
            jaw.view(1, 1, 3),
            leye.view(1, 1, 3),
            reye.view(1, 1, 3),
            left_hand.view(1, 15, 3),
            right_hand.view(1, 15, 3),
        ], dim=1).reshape(1, -1)
        full_pose = full_pose + model.pose_mean
        rot_mats = batch_rodrigues(full_pose.view(-1, 3)).view(1, -1, 3, 3)
        ident = torch.eye(3, dtype=torch.float32, device=device)
        pose_feature = (rot_mats[:, 1:] - ident).reshape(1, -1)
        pose_offsets = torch.matmul(pose_feature, model.posedirs).view(1, -1, 3)
        _, transforms = batch_rigid_transform(rot_mats, rest_joints, model.parents, dtype=torch.float32)

        reco = torch.tensor(reco_obj, dtype=torch.float32, device=device)
        donor = posed_model
        weights = model.lbs_weights

        donor_top_weight, donor_top_joint = torch.topk(weights, k=4, dim=1)
        donor_top_weight = donor_top_weight / donor_top_weight.sum(dim=1, keepdim=True)
        compatible_indices: dict[str, Any] = {}
        output_forbidden_mass: dict[str, Any] = {}
        for region in LIMB_REGIONS:
            indices = forbidden_joint_indices(base.SMPLX_JOINT_NAMES, region)
            if not indices:
                raise base.FitterError(f"SMPL-X anatomy guard has no forbidden joints for {region}")
            forbidden = torch.tensor(indices, dtype=torch.long, device=device)
            forbidden_mask = (donor_top_joint.unsqueeze(-1) == forbidden.view(1, 1, -1)).any(dim=-1)
            mass = (donor_top_weight * forbidden_mask.to(donor_top_weight.dtype)).sum(dim=1)
            candidates = torch.nonzero(mass <= ANATOMY_GUARD_THRESHOLD, as_tuple=False).flatten()
            if int(candidates.numel()) == 0:
                raise base.FitterError(f"SMPL-X anatomy guard has no compatible donors for {region}")
            output_forbidden_mass[region] = mass
            compatible_indices[region] = candidates

        transform_table = transforms[0].reshape(len(base.SMPLX_JOINT_NAMES), 16)

        def unskin(chunk: Any, selected: Any) -> tuple[Any, Any, Any, Any]:
            full_weights = weights[selected]
            transform = torch.matmul(full_weights, transform_table).view(-1, 4, 4)
            model_space = chunk / scale - transl[0]
            homogeneous = torch.cat(
                [model_space, torch.ones((len(chunk), 1), dtype=torch.float32, device=device)],
                dim=1,
            ).unsqueeze(-1)
            try:
                inverse = torch.linalg.inv(transform)
            except RuntimeError as exc:
                raise base.FitterError("SMPL-X blended skin transform is singular") from exc
            unskinned = torch.matmul(inverse, homogeneous)[:, :3, 0]
            rest = unskinned - pose_offsets[0, selected]
            top_weight, top_joint = torch.topk(full_weights, k=4, dim=1)
            totals = top_weight.sum(dim=1, keepdim=True)
            if bool(torch.any(totals <= 1e-8).item()):
                raise base.FitterError("SMPL-X skin weights contain an empty influence set")
            top_weight = top_weight / totals
            return rest, top_joint, top_weight, full_weights

        # Phase A: reproduce the historical nearest-neighbour transfer exactly.
        # The anatomy decision must be made later in the same final rest-pose
        # coordinate domain that production skin-QA inspects, not in posed space.
        default_rest_chunks: list[Any] = []
        default_joint_chunks: list[Any] = []
        default_weight_chunks: list[Any] = []
        nearest_chunks: list[Any] = []
        distance_chunks: list[Any] = []
        chunk_size = 768
        for start in range(0, int(reco.shape[0]), chunk_size):
            chunk = reco[start:start + chunk_size]
            distances = torch.cdist(chunk.unsqueeze(0), donor.unsqueeze(0)).squeeze(0)
            nearest_distance, nearest = torch.min(distances, dim=1)
            rest, top_joint, top_weight, _ = unskin(chunk, nearest)
            default_rest_chunks.append(rest.detach().cpu())
            default_joint_chunks.append(top_joint.detach().cpu())
            default_weight_chunks.append(top_weight.detach().cpu())
            nearest_chunks.append(nearest.detach().cpu())
            distance_chunks.append(nearest_distance.detach().cpu())

        default_rest_positions = torch.cat(default_rest_chunks, dim=0).numpy()
        default_joints4 = torch.cat(default_joint_chunks, dim=0).numpy()
        default_weights4 = torch.cat(default_weight_chunks, dim=0).numpy()
        selected_nearest = torch.cat(nearest_chunks, dim=0).to(device=device, dtype=torch.long)
        default_distance_all = torch.cat(distance_chunks, dim=0).to(device=device, dtype=torch.float32)
        selected_distance_all = default_distance_all.clone()

        provisional_positions = default_rest_positions
        provisional_joints = rest_joints_np
        if _CURRENT_ADJUSTMENT is not None:
            try:
                provisional_positions, provisional_joints, _ = apply_shape_adjustment(
                    np=np,
                    rest_positions=default_rest_positions,
                    rest_joints=rest_joints_np,
                    joints4=default_joints4,
                    weights4=default_weights4,
                    joint_names=base.SMPLX_JOINT_NAMES,
                    adjustment=_CURRENT_ADJUSTMENT,
                )
            except BodyprintAdjustmentError as exc:
                raise base.FitterError(f"BodyPrint provisional shape adjustment failed: {exc}") from exc

        try:
            target_regions, body_scale = classify_strong_limb_regions(
                provisional_positions.tolist(),
                provisional_joints.tolist(),
                parents,
                base.SMPLX_JOINT_NAMES,
            )
        except ValueError as exc:
            raise base.FitterError(f"SMPL-X anatomy guard rest-space classification failed: {exc}") from exc

        guarded_global: set[int] = set()
        guarded_extras: list[Any] = []
        guarded_distances: list[Any] = []
        for region in LIMB_REGIONS:
            rows = [
                index
                for index, candidate in enumerate(target_regions)
                if candidate == region
                and float(output_forbidden_mass[region][selected_nearest[index]].item()) > ANATOMY_GUARD_THRESHOLD
            ]
            if not rows:
                continue
            candidates = compatible_indices[region]
            for start in range(0, len(rows), chunk_size):
                batch_rows = rows[start:start + chunk_size]
                row_tensor = torch.tensor(batch_rows, dtype=torch.long, device=device)
                candidate_distances = torch.cdist(
                    reco[row_tensor].unsqueeze(0),
                    donor[candidates].unsqueeze(0),
                ).squeeze(0)
                replacement_distance, replacement_local = torch.min(candidate_distances, dim=1)
                replacement_donor = candidates[replacement_local]
                original_distance = default_distance_all[row_tensor]
                extra = replacement_distance - original_distance
                absolute_limit = body_scale * MAX_GUARD_DISTANCE_SCALE
                excessive = (
                    (extra > body_scale * MAX_GUARD_EXTRA_SCALE)
                    & (replacement_distance > original_distance * MAX_GUARD_DISTANCE_RATIO)
                    & (replacement_distance > absolute_limit)
                )
                if bool(torch.any(excessive).item()):
                    worst = int(torch.argmax(extra).item())
                    raise base.FitterError(
                        "SMPL-X anatomy guard compatible donor is implausibly far "
                        f"for {region} (default={float(original_distance[worst].item()):.4f}, "
                        f"guarded={float(replacement_distance[worst].item()):.4f}, "
                        f"body_scale={body_scale:.4f})"
                    )
                selected_nearest[row_tensor] = replacement_donor
                selected_distance_all[row_tensor] = replacement_distance
                guarded_global.update(batch_rows)
                guarded_extras.append(extra.detach().cpu())
                guarded_distances.append(replacement_distance.detach().cpu())

        # Phase B: materialize the final rest mesh from the selected donors.
        rest_chunks: list[Any] = []
        joint_chunks: list[Any] = []
        weight_chunks: list[Any] = []
        for start in range(0, int(reco.shape[0]), chunk_size):
            chunk = reco[start:start + chunk_size]
            selected = selected_nearest[start:start + len(chunk)]
            rest, top_joint, top_weight, _ = unskin(chunk, selected)
            rest_chunks.append(rest.detach().cpu())
            joint_chunks.append(top_joint.detach().cpu())
            weight_chunks.append(top_weight.detach().cpu())

        rest_positions = torch.cat(rest_chunks, dim=0).numpy()
        joints4 = torch.cat(joint_chunks, dim=0).numpy()
        weights4 = torch.cat(weight_chunks, dim=0).numpy()

        adjustment_metrics: dict[str, float] = {"max_joint_delta": 0.0}
        final_joints = rest_joints_np
        if _CURRENT_ADJUSTMENT is not None:
            try:
                rest_positions, final_joints, adjustment_metrics = apply_shape_adjustment(
                    np=np,
                    rest_positions=rest_positions,
                    rest_joints=rest_joints_np,
                    joints4=joints4,
                    weights4=weights4,
                    joint_names=base.SMPLX_JOINT_NAMES,
                    adjustment=_CURRENT_ADJUSTMENT,
                )
            except BodyprintAdjustmentError as exc:
                raise base.FitterError(f"BodyPrint shape adjustment failed: {exc}") from exc

        # Fail closed inside the bridge using the same final rest-pose geometry
        # semantics as skin-QA. We deliberately do not relax QA thresholds.
        try:
            final_regions, _ = classify_strong_limb_regions(
                rest_positions.tolist(),
                final_joints.tolist(),
                parents,
                base.SMPLX_JOINT_NAMES,
            )
        except ValueError as exc:
            raise base.FitterError(f"SMPL-X anatomy guard final classification failed: {exc}") from exc

        final_violations: list[tuple[int, str, float]] = []
        for index, region in enumerate(final_regions):
            if region is None:
                continue
            mass = float(output_forbidden_mass[region][selected_nearest[index]].item())
            if mass > ANATOMY_GUARD_THRESHOLD + 1e-6:
                final_violations.append((index, region, mass))
        if final_violations:
            worst = max(final_violations, key=lambda item: item[2])
            raise base.FitterError(
                "SMPL-X anatomy guard final rest-pose validation failed "
                f"(violations={len(final_violations)}, vertex={worst[0]}, "
                f"region={worst[1]}, forbidden_weight={worst[2]:.6f})"
            )

        nearest_all = selected_distance_all.detach().cpu().numpy()
        nearest_p95 = float(np.quantile(nearest_all, 0.95))
        nearest_max = float(np.max(nearest_all))
        if not math.isfinite(nearest_p95) or not math.isfinite(nearest_max):
            raise base.FitterError("SMPL-X nearest-surface quality is non-finite")
        if nearest_p95 > 0.30 or nearest_max > 0.85:
            raise base.FitterError(
                f"SiTH mesh is too far from the fitted SMPL-X surface (p95={nearest_p95:.4f}, max={nearest_max:.4f})"
            )

        guarded_vertex_count = len(guarded_global)
        if guarded_vertex_count:
            guarded_extra_all = torch.cat(guarded_extras).numpy()
            guarded_distance_all = torch.cat(guarded_distances).numpy()
            guarded_extra_p95 = float(np.quantile(guarded_extra_all, 0.95))
            guarded_extra_max = float(np.max(guarded_extra_all))
            guarded_distance_max = float(np.max(guarded_distance_all))
        else:
            guarded_extra_p95 = 0.0
            guarded_extra_max = 0.0
            guarded_distance_max = 0.0

    quality = {
        "nearest_p95": nearest_p95,
        "nearest_max": nearest_max,
        "adjustment_max_joint_delta": float(adjustment_metrics.get("max_joint_delta", 0.0)),
        "anatomy_guarded_vertex_count": float(guarded_vertex_count),
        "anatomy_guard_extra_p95": guarded_extra_p95,
        "anatomy_guard_extra_max": guarded_extra_max,
        "anatomy_guard_distance_max": guarded_distance_max,
    }
    print(
        "BodyRig anatomy guard: "
        f"guarded={guarded_vertex_count} "
        f"extra_p95={guarded_extra_p95:.6f} "
        f"extra_max={guarded_extra_max:.6f} "
        f"guarded_distance_max={guarded_distance_max:.6f}",
        file=sys.stderr,
    )
    texture = paths["texture"].read_bytes()
    return (*base._build_vrm(
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
    ), quality)


base._validate_request = _validate_request
base._rig_mesh = _rig_mesh

if __name__ == "__main__":
    raise SystemExit(base.main())
