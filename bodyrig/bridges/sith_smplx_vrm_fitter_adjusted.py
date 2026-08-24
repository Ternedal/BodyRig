#!/usr/bin/env python
"""BodyRig SiTH fitter entrypoint with bounded reviewed BodyPrint adjustments.

This is a thin one-shot wrapper around sith_smplx_vrm_fitter.py. The original
standalone bridge remains the source-derived fitter authority; this wrapper only
adds optional, bounded rest-pose proportion deltas before the existing VRM
builder serializes the mesh.
"""
from __future__ import annotations

import math
from typing import Any

import sith_smplx_vrm_fitter as base
from bodyprint_shape_adjust import (
    BodyprintAdjustmentError,
    apply_shape_adjustment,
    validate_adjustment_payload,
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
        rest_chunks: list[Any] = []
        joint_chunks: list[Any] = []
        weight_chunks: list[Any] = []
        nearest_distances: list[Any] = []
        chunk_size = 768
        for start in range(0, int(reco.shape[0]), chunk_size):
            chunk = reco[start:start + chunk_size]
            distances = torch.cdist(chunk.unsqueeze(0), donor.unsqueeze(0)).squeeze(0)
            nearest_distance, nearest = torch.min(distances, dim=1)
            nearest_distances.append(nearest_distance.detach().cpu())
            full_weights = weights[nearest]
            transform = torch.matmul(full_weights, transforms[0].reshape(len(base.SMPLX_JOINT_NAMES), 16)).view(-1, 4, 4)
            model_space = chunk / scale - transl[0]
            homogeneous = torch.cat([model_space, torch.ones((len(chunk), 1), device=device)], dim=1).unsqueeze(-1)
            try:
                inverse = torch.linalg.inv(transform)
            except RuntimeError as exc:
                raise base.FitterError("SMPL-X blended skin transform is singular") from exc
            unskinned = torch.matmul(inverse, homogeneous)[:, :3, 0]
            rest = unskinned - pose_offsets[0, nearest]
            top_weight, top_joint = torch.topk(full_weights, k=4, dim=1)
            totals = top_weight.sum(dim=1, keepdim=True)
            if bool(torch.any(totals <= 1e-8).item()):
                raise base.FitterError("SMPL-X skin weights contain an empty influence set")
            top_weight = top_weight / totals
            rest_chunks.append(rest.detach().cpu())
            joint_chunks.append(top_joint.detach().cpu())
            weight_chunks.append(top_weight.detach().cpu())

        rest_positions = torch.cat(rest_chunks, dim=0).numpy()
        joints4 = torch.cat(joint_chunks, dim=0).numpy()
        weights4 = torch.cat(weight_chunks, dim=0).numpy()
        nearest_all = torch.cat(nearest_distances).numpy()
        nearest_p95 = float(np.quantile(nearest_all, 0.95))
        nearest_max = float(np.max(nearest_all))
        if not math.isfinite(nearest_p95) or not math.isfinite(nearest_max):
            raise base.FitterError("SMPL-X nearest-surface quality is non-finite")
        if nearest_p95 > 0.30 or nearest_max > 0.85:
            raise base.FitterError(
                f"SiTH mesh is too far from the fitted SMPL-X surface (p95={nearest_p95:.4f}, max={nearest_max:.4f})"
            )

    rest_joints_np = rest_joints[0].detach().cpu().numpy()
    adjustment_metrics: dict[str, float] = {"max_joint_delta": 0.0}
    if _CURRENT_ADJUSTMENT is not None:
        try:
            rest_positions, rest_joints_np, adjustment_metrics = apply_shape_adjustment(
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

    quality = {
        "nearest_p95": nearest_p95,
        "nearest_max": nearest_max,
        "adjustment_max_joint_delta": float(adjustment_metrics.get("max_joint_delta", 0.0)),
    }
    texture = paths["texture"].read_bytes()
    return (*base._build_vrm(
        np=np,
        name=name,
        rest_positions=rest_positions,
        texcoords=texcoords,
        faces=faces,
        joints4=joints4,
        weights4=weights4,
        rest_joints=rest_joints_np,
        parents=parents,
        texture_png=texture,
        quality=quality,
    ), quality)


base._validate_request = _validate_request
base._rig_mesh = _rig_mesh

if __name__ == "__main__":
    raise SystemExit(base.main())
