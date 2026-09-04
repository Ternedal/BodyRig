#!/usr/bin/env python
"""Build a comparison-only VRM with source-derived hair on the exact body skin.

The base avatar remains immutable. Hair is inverse-skinned from the retained SiTH
posed source shell into the exact SMPL-X rest pose, receives the same bounded
BodyPrint geometry replay as the body when present, and is appended as a second
skinned mesh for physical silhouette review. The output is never component or
production authority.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import struct
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

import sith_smplx_vrm_fitter as base
from bodyprint_shape_adjust import (
    ADJUSTMENT_FORMAT,
    ADJUSTMENT_VERSION,
    BodyprintAdjustmentError,
    apply_shape_adjustment,
)
from sith_pbr_material import PbrMaterialError, _read_glb, _write_glb

FORMAT = "bodyrig-source-hair-review-bridge"
VERSION = 1
BINDING_FORMAT = "bodyrig-source-hair-body-binding"
BINDING_VERSION = 1
GEOMETRY_FORMAT = "bodyrig-sith-body-geometry-authority"
GEOMETRY_VERSION = 2
GEOMETRY_METHOD = "exact-sith-reconstruction-bytes-v2"
REPLAY_METHOD = "bodyrig-bodyprint-shape-adjust-v1"
SHA256_LENGTH = 64
FIT_MAX_THRESHOLD = 0.005
FIT_RMS_THRESHOLD = 0.001
NEAREST_P95_THRESHOLD = 0.30
NEAREST_MAX_THRESHOLD = 0.85


class HairReviewRuntimeError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda token: (_ for _ in ()).throw(ValueError(token)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise HairReviewRuntimeError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise HairReviewRuntimeError(f"{label} must be an object")
    return value


def _sha(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != SHA256_LENGTH
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise HairReviewRuntimeError(f"{label} is invalid")
    return value


def _safe_leaf(value: Any, *, label: str) -> str:
    if not isinstance(value, str):
        raise HairReviewRuntimeError(f"{label} is invalid")
    name = value.strip()
    if not name or name in {".", ".."} or Path(name).name != name or "/" in name or "\\" in name:
        raise HairReviewRuntimeError(f"{label} must be a safe leaf filename")
    return name


def _geometry(document: Mapping[str, Any]) -> dict[str, Any]:
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    geometry = bodyrig.get("sourceGeometryAuthority") if isinstance(bodyrig, dict) else None
    if not isinstance(geometry, dict):
        raise HairReviewRuntimeError("base avatar lacks SiTH source geometry authority")
    required = {
        "format", "version", "method", "reconstructionSha256", "reconstructionAuthoritySha256",
        "bodyModelGender", "smplxFitProfile", "fittedDonorObjSha256", "fitParamsSha256",
        "sourceMeshSha256", "sourceMaterialSha256", "sourceTextureSha256", "sourceTextureName",
        "bodyprintGeometryAdjustment", "exactByteBinding", "hairCandidateBindingEligible",
        "productionActivation",
    }
    if set(geometry) != required:
        raise HairReviewRuntimeError("base avatar geometry authority fields do not match v2")
    if (
        geometry.get("format") != GEOMETRY_FORMAT
        or geometry.get("version") != GEOMETRY_VERSION
        or geometry.get("method") != GEOMETRY_METHOD
        or geometry.get("exactByteBinding") is not True
        or geometry.get("hairCandidateBindingEligible") is not True
        or geometry.get("productionActivation") is not False
    ):
        raise HairReviewRuntimeError("base avatar geometry authority is not hair-review eligible")
    for field in (
        "reconstructionSha256", "reconstructionAuthoritySha256", "fittedDonorObjSha256",
        "fitParamsSha256", "sourceMeshSha256", "sourceMaterialSha256", "sourceTextureSha256",
    ):
        _sha(geometry.get(field), label=f"geometry {field}")
    if geometry.get("bodyModelGender") not in {"female", "male", "neutral"}:
        raise HairReviewRuntimeError("base avatar body model family is invalid")
    _safe_leaf(geometry.get("sourceTextureName"), label="base avatar source texture")
    replay = geometry.get("bodyprintGeometryAdjustment")
    if not isinstance(replay, dict) or set(replay) != {"method", "applied", "evidenceSha256", "changes"}:
        raise HairReviewRuntimeError("base avatar BodyPrint geometry replay is invalid")
    if replay.get("method") != REPLAY_METHOD or not isinstance(replay.get("applied"), bool):
        raise HairReviewRuntimeError("base avatar BodyPrint geometry replay method/state is invalid")
    changes = replay.get("changes")
    if not isinstance(changes, list):
        raise HairReviewRuntimeError("base avatar BodyPrint geometry replay changes are invalid")
    if bool(changes) is not replay["applied"]:
        raise HairReviewRuntimeError("base avatar BodyPrint geometry replay applied flag is inconsistent")
    if changes:
        _sha(replay.get("evidenceSha256"), label="BodyPrint geometry replay evidenceSha256")
    elif replay.get("evidenceSha256") is not None:
        _sha(replay.get("evidenceSha256"), label="BodyPrint geometry replay evidenceSha256")
    return dict(geometry)


def _binding(path: Path, *, avatar_sha: str, geometry: Mapping[str, Any]) -> dict[str, Any]:
    value = _load_json(path, label="source hair body binding")
    required = {
        "format", "version", "bodyId", "packageSha256", "avatarVrmSha256",
        "sourceGeometryAuthority", "hairCandidateReceiptSha256", "hairObjSha256",
        "hairMaterialSha256", "hairTextureSha256", "bindingStatus",
        "runtimeIntegrationRequired", "physicalSilhouetteReviewRequired", "comparisonOnly",
        "humanReviewRequired", "productionActivation",
    }
    if set(value) != required or value.get("format") != BINDING_FORMAT or value.get("version") != BINDING_VERSION:
        raise HairReviewRuntimeError("source hair body binding fields do not match v1")
    if value.get("avatarVrmSha256") != avatar_sha:
        raise HairReviewRuntimeError("source hair body binding targets different avatar bytes")
    if value.get("sourceGeometryAuthority") != geometry:
        raise HairReviewRuntimeError("source hair body binding geometry authority differs from base avatar")
    for field in (
        "packageSha256", "avatarVrmSha256", "hairCandidateReceiptSha256", "hairObjSha256",
        "hairMaterialSha256", "hairTextureSha256",
    ):
        _sha(value.get(field), label=f"binding {field}")
    if (
        value.get("bindingStatus") != "exact-source-and-donor-match"
        or value.get("runtimeIntegrationRequired") is not True
        or value.get("physicalSilhouetteReviewRequired") is not True
        or value.get("comparisonOnly") is not True
        or value.get("humanReviewRequired") is not True
        or value.get("productionActivation") is not False
    ):
        raise HairReviewRuntimeError("source hair body binding is not a non-activating review binding")
    return value


def _validate_exact_inputs(
    *,
    workspace: Path,
    candidate_dir: Path,
    geometry: Mapping[str, Any],
    binding: Mapping[str, Any],
) -> tuple[Path, Path, Path, Path]:
    stage = workspace / "sith-input-v1"
    texture_name = _safe_leaf(geometry["sourceTextureName"], label="source texture")
    artifacts = {
        "reconstructionSha256": stage / "reconstruction.json",
        "reconstructionAuthoritySha256": stage / "reconstruction-authority.json",
        "fittedDonorObjSha256": stage / "smplx" / "000_smplx.obj",
        "fitParamsSha256": stage / "smplx" / "000_fit.json",
        "sourceMeshSha256": stage / "meshes" / "000_reco.obj",
        "sourceMaterialSha256": stage / "meshes" / "000.mtl",
        "sourceTextureSha256": stage / "meshes" / texture_name,
    }
    for field, path in artifacts.items():
        if not path.is_file() or _sha256(path) != geometry[field]:
            raise HairReviewRuntimeError(f"candidate workspace byte hash mismatch: {field}")

    hair_obj = candidate_dir / "hair_source.obj"
    hair_mtl = candidate_dir / "000.mtl"
    hair_texture = candidate_dir / texture_name
    candidate_receipt = candidate_dir / "source-hair-candidate.json"
    for path in (hair_obj, hair_mtl, hair_texture, candidate_receipt):
        if not path.is_file():
            raise HairReviewRuntimeError(f"hair candidate artifact is missing: {path.name}")
    checks = (
        (hair_obj, "hairObjSha256"),
        (hair_mtl, "hairMaterialSha256"),
        (hair_texture, "hairTextureSha256"),
        (candidate_receipt, "hairCandidateReceiptSha256"),
    )
    for path, field in checks:
        if _sha256(path) != binding[field]:
            raise HairReviewRuntimeError(f"hair candidate byte hash mismatch: {field}")
    return artifacts["fittedDonorObjSha256"], artifacts["fitParamsSha256"], hair_obj, hair_texture


def _transient_adjustment(replay: Mapping[str, Any]) -> dict[str, Any] | None:
    if replay.get("applied") is not True:
        return None
    evidence = _sha(replay.get("evidenceSha256"), label="BodyPrint replay evidence")
    changes = replay.get("changes")
    if not isinstance(changes, list) or not changes:
        raise HairReviewRuntimeError("BodyPrint replay is applied without geometry changes")
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(changes):
        if not isinstance(item, dict) or set(item) != {"field", "delta"}:
            raise HairReviewRuntimeError(f"BodyPrint replay changes[{index}] is invalid")
        normalized.append({
            "field": item["field"],
            "delta": item["delta"],
            "reason": "portable geometry authority replay",
        })
    return {
        "format": ADJUSTMENT_FORMAT,
        "version": ADJUSTMENT_VERSION,
        "feedback_sha256": evidence,
        "changes": normalized,
    }


def _inverse_skin_hair(
    *,
    workspace: Path,
    hair_obj: Path,
    model_dir: str,
    gender: str,
    replay: Mapping[str, Any],
) -> tuple[Any, list[tuple[float, float]], list[list[tuple[int, int]]], Any, Any, Any, list[int], dict[str, float]]:
    try:
        import numpy as np
        import torch
        from smplx import SMPLX
        from smplx.lbs import batch_rigid_transform, batch_rodrigues, blend_shapes, vertices2joints
    except ImportError as exc:
        raise HairReviewRuntimeError(f"hair review runtime dependencies are unavailable: {exc}") from exc
    if not torch.cuda.is_available():
        raise HairReviewRuntimeError("hair review inverse skinning requires CUDA")

    stage = workspace / "sith-input-v1"
    donor_path = stage / "smplx" / "000_smplx.obj"
    params_path = stage / "smplx" / "000_fit.json"
    params = base._fit_params(params_path)
    donor_obj = np.asarray(base._parse_positions(donor_path), dtype=np.float32)
    hair_positions_list, texcoords, faces = base._parse_textured_obj(hair_obj)
    hair_obj_arr = np.asarray(hair_positions_list, dtype=np.float32)
    device = torch.device("cuda")

    try:
        model = SMPLX(
            model_path=model_dir,
            gender=gender,
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        ).to(device)
    except Exception as exc:
        raise HairReviewRuntimeError(f"failed to load licensed SMPL-X {gender} model") from exc
    model.eval()
    if int(model.lbs_weights.shape[0]) != len(donor_obj) or int(model.lbs_weights.shape[1]) != len(base.SMPLX_JOINT_NAMES):
        raise HairReviewRuntimeError("SMPL-X model topology does not match candidate donor")
    parents = [int(value) for value in model.parents.detach().cpu().tolist()]
    if len(parents) != len(base.SMPLX_JOINT_NAMES) or parents[0] != -1:
        raise HairReviewRuntimeError("SMPL-X parent topology is incompatible with BodyRig")

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
    if not math.isfinite(scale) or scale <= 0.0:
        raise HairReviewRuntimeError("candidate SMPL-X scale is invalid")

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
        fit_delta = torch.linalg.vector_norm(posed_model - donor_tensor, dim=1)
        fit_max = float(fit_delta.max().item())
        fit_rms = float(torch.sqrt(torch.mean(fit_delta * fit_delta)).item())
        if fit_max > FIT_MAX_THRESHOLD or fit_rms > FIT_RMS_THRESHOLD:
            raise HairReviewRuntimeError("candidate fit parameters do not reproduce the exact donor OBJ")

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

        hair = torch.tensor(hair_obj_arr, dtype=torch.float32, device=device)
        weights = model.lbs_weights
        rest_chunks: list[Any] = []
        joint_chunks: list[Any] = []
        weight_chunks: list[Any] = []
        nearest_chunks: list[Any] = []
        for start in range(0, int(hair.shape[0]), 512):
            chunk = hair[start:start + 512]
            distances = torch.cdist(chunk.unsqueeze(0), posed_model.unsqueeze(0)).squeeze(0)
            nearest_distance, nearest = torch.min(distances, dim=1)
            nearest_chunks.append(nearest_distance.detach().cpu())
            full_weights = weights[nearest]
            transform = torch.matmul(
                full_weights,
                transforms[0].reshape(len(base.SMPLX_JOINT_NAMES), 16),
            ).view(-1, 4, 4)
            model_space = chunk / scale - transl[0]
            homogeneous = torch.cat(
                [model_space, torch.ones((len(chunk), 1), dtype=torch.float32, device=device)],
                dim=1,
            ).unsqueeze(-1)
            try:
                inverse = torch.linalg.inv(transform)
            except RuntimeError as exc:
                raise HairReviewRuntimeError("hair blended SMPL-X skin transform is singular") from exc
            unskinned = torch.matmul(inverse, homogeneous)[:, :3, 0]
            rest = unskinned - pose_offsets[0, nearest]
            top_weight, top_joint = torch.topk(full_weights, k=4, dim=1)
            totals = top_weight.sum(dim=1, keepdim=True)
            if bool(torch.any(totals <= 1e-8).item()):
                raise HairReviewRuntimeError("hair skin weights contain an empty influence set")
            top_weight = top_weight / totals
            rest_chunks.append(rest.detach().cpu())
            joint_chunks.append(top_joint.detach().cpu())
            weight_chunks.append(top_weight.detach().cpu())

    rest_positions = torch.cat(rest_chunks, dim=0).numpy()
    joints4 = torch.cat(joint_chunks, dim=0).numpy()
    weights4 = torch.cat(weight_chunks, dim=0).numpy()
    final_joints = rest_joints[0].detach().cpu().numpy().astype(np.float32, copy=True)
    adjustment_metrics: dict[str, float] = {"max_joint_delta": 0.0}
    adjustment = _transient_adjustment(replay)
    if adjustment is not None:
        try:
            rest_positions, final_joints, adjustment_metrics = apply_shape_adjustment(
                np=np,
                rest_positions=rest_positions,
                rest_joints=final_joints,
                joints4=joints4,
                weights4=weights4,
                joint_names=base.SMPLX_JOINT_NAMES,
                adjustment=adjustment,
            )
        except BodyprintAdjustmentError as exc:
            raise HairReviewRuntimeError(f"hair BodyPrint geometry replay failed: {exc}") from exc

    nearest = torch.cat(nearest_chunks).numpy()
    nearest_p95 = float(np.quantile(nearest, 0.95))
    nearest_max = float(np.max(nearest))
    if not math.isfinite(nearest_p95) or not math.isfinite(nearest_max):
        raise HairReviewRuntimeError("hair nearest-donor distance is non-finite")
    if nearest_p95 > NEAREST_P95_THRESHOLD or nearest_max > NEAREST_MAX_THRESHOLD:
        raise HairReviewRuntimeError(
            f"source hair is too far from candidate donor for review runtime (p95={nearest_p95:.6f}, max={nearest_max:.6f})"
        )
    metrics = {
        "fit_max": fit_max,
        "fit_rms": fit_rms,
        "nearest_p95": nearest_p95,
        "nearest_max": nearest_max,
        "bodyprint_max_joint_delta": float(adjustment_metrics.get("max_joint_delta", 0.0)),
    }
    return rest_positions, texcoords, faces, joints4, weights4, final_joints, parents, metrics


def _verify_avatar_skeleton(document: Mapping[str, Any], *, final_joints: Any, parents: Sequence[int]) -> None:
    nodes = document.get("nodes")
    skins = document.get("skins")
    if not isinstance(nodes, list) or not isinstance(skins, list) or len(skins) != 1 or not isinstance(skins[0], dict):
        raise HairReviewRuntimeError("base avatar skin contract is unsupported")
    skin = skins[0]
    expected_joints = list(range(len(base.SMPLX_JOINT_NAMES)))
    if skin.get("joints") != expected_joints or skin.get("skeleton") != 0:
        raise HairReviewRuntimeError("base avatar does not expose canonical SMPL-X skin 0")
    if len(nodes) < len(expected_joints):
        raise HairReviewRuntimeError("base avatar is missing SMPL-X joint nodes")

    global_positions: list[list[float]] = []
    for index, joint_name in enumerate(base.SMPLX_JOINT_NAMES):
        node = nodes[index]
        if not isinstance(node, dict) or node.get("name") != f"smplx_{joint_name}":
            raise HairReviewRuntimeError("base avatar SMPL-X node order/name is incompatible")
        translation = node.get("translation")
        if (
            not isinstance(translation, list)
            or len(translation) != 3
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)) for value in translation)
        ):
            raise HairReviewRuntimeError("base avatar SMPL-X node translation is invalid")
        local = [float(value) for value in translation]
        parent = int(parents[index])
        if index == 0:
            if parent != -1:
                raise HairReviewRuntimeError("SMPL-X root parent is invalid")
            global_positions.append(local)
        else:
            if parent < 0 or parent >= index:
                raise HairReviewRuntimeError("SMPL-X parent topology is invalid")
            global_positions.append([
                global_positions[parent][axis] + local[axis]
                for axis in range(3)
            ])

    for index, actual in enumerate(global_positions):
        expected = [float(value) for value in final_joints[index]]
        delta = math.sqrt(sum((actual[axis] - expected[axis]) ** 2 for axis in range(3)))
        if delta > 1e-5:
            raise HairReviewRuntimeError(
                f"hair rest skeleton differs from base avatar at joint {base.SMPLX_JOINT_NAMES[index]} (delta={delta:.8f})"
            )


def _append_hair_mesh(
    *,
    document: dict[str, Any],
    binary_bytes: bytes,
    rest_positions: Any,
    texcoords: Sequence[Sequence[float]],
    faces: Sequence[Sequence[tuple[int, int]]],
    joints4: Any,
    weights4: Any,
    texture_png: bytes,
    metadata: Mapping[str, Any],
) -> tuple[bytes, int, int, int]:
    try:
        import numpy as np
    except ImportError as exc:
        raise HairReviewRuntimeError(f"numpy is required for hair review GLB serialization: {exc}") from exc
    arrays = {
        "bufferViews": document.get("bufferViews"),
        "accessors": document.get("accessors"),
        "images": document.get("images"),
        "textures": document.get("textures"),
        "materials": document.get("materials"),
        "meshes": document.get("meshes"),
        "nodes": document.get("nodes"),
        "scenes": document.get("scenes"),
        "samplers": document.get("samplers"),
        "buffers": document.get("buffers"),
    }
    if any(not isinstance(value, list) for value in arrays.values()):
        raise HairReviewRuntimeError("base avatar glTF arrays are incomplete")
    views = arrays["bufferViews"]
    accessors = arrays["accessors"]
    images = arrays["images"]
    textures = arrays["textures"]
    materials = arrays["materials"]
    meshes = arrays["meshes"]
    nodes = arrays["nodes"]
    scenes = arrays["scenes"]
    samplers = arrays["samplers"]
    buffers = arrays["buffers"]
    assert isinstance(views, list) and isinstance(accessors, list) and isinstance(images, list)
    assert isinstance(textures, list) and isinstance(materials, list) and isinstance(meshes, list)
    assert isinstance(nodes, list) and isinstance(scenes, list) and isinstance(samplers, list) and isinstance(buffers, list)
    if len(samplers) < 1 or len(buffers) != 1 or not isinstance(buffers[0], dict):
        raise HairReviewRuntimeError("base avatar sampler/buffer contract is unsupported")
    if not scenes or not isinstance(scenes[0], dict) or not isinstance(scenes[0].get("nodes"), list):
        raise HairReviewRuntimeError("base avatar scene contract is unsupported")

    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict):
        raise HairReviewRuntimeError("base avatar BodyRig metadata is missing")
    if "hairReviewRuntime" in bodyrig:
        raise HairReviewRuntimeError("base avatar already contains a hair review runtime")

    vertex_map: dict[tuple[int, int], int] = {}
    positions_out: list[Any] = []
    uv_out: list[tuple[float, float]] = []
    joints_out: list[Any] = []
    weights_out: list[Any] = []
    indices: list[int] = []
    for face in faces:
        if len(face) != 3:
            raise HairReviewRuntimeError("hair review topology is not triangular")
        for vertex_index, uv_index in face:
            if vertex_index < 0 or vertex_index >= len(rest_positions) or uv_index < 0 or uv_index >= len(texcoords):
                raise HairReviewRuntimeError("hair review face index is outside range")
            key = (int(vertex_index), int(uv_index))
            mapped = vertex_map.get(key)
            if mapped is None:
                mapped = len(positions_out)
                vertex_map[key] = mapped
                positions_out.append(rest_positions[vertex_index])
                u, v = texcoords[uv_index]
                uv_out.append((float(u), float(1.0 - v)))
                joints_out.append(joints4[vertex_index])
                weights_out.append(weights4[vertex_index])
            indices.append(mapped)

    positions_arr = np.asarray(positions_out, dtype=np.float32)
    uv_arr = np.asarray(uv_out, dtype=np.float32)
    joints_arr = np.asarray(joints_out, dtype=np.uint16)
    weights_arr = np.asarray(weights_out, dtype=np.float32)
    indices_arr = np.asarray(indices, dtype=np.uint32)
    if len(positions_arr) < 3 or indices_arr.size < 3:
        raise HairReviewRuntimeError("hair review mesh contains too little geometry")

    normals = np.zeros_like(positions_arr)
    for a, b, c in indices_arr.reshape(-1, 3):
        edge1 = positions_arr[b] - positions_arr[a]
        edge2 = positions_arr[c] - positions_arr[a]
        normal = np.cross(edge1, edge2)
        normals[a] += normal
        normals[b] += normal
        normals[c] += normal
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1e-12
    normals[valid] /= lengths[valid, None]
    normals[~valid] = np.asarray([0.0, 1.0, 0.0], dtype=np.float32)

    binary = bytearray(binary_bytes)

    def add_view(raw: bytes, *, target: int | None = None) -> int:
        while len(binary) % 4:
            binary.append(0)
        offset = len(binary)
        binary.extend(raw)
        view: dict[str, Any] = {"buffer": 0, "byteOffset": offset, "byteLength": len(raw)}
        if target is not None:
            view["target"] = target
        views.append(view)
        return len(views) - 1

    def add_accessor(
        raw: bytes,
        *,
        component: int,
        count: int,
        kind: str,
        target: int | None = None,
        minimum: list[float] | None = None,
        maximum: list[float] | None = None,
    ) -> int:
        view = add_view(raw, target=target)
        accessor: dict[str, Any] = {
            "bufferView": view,
            "componentType": component,
            "count": count,
            "type": kind,
        }
        if minimum is not None:
            accessor["min"] = minimum
        if maximum is not None:
            accessor["max"] = maximum
        accessors.append(accessor)
        return len(accessors) - 1

    pos_accessor = add_accessor(
        positions_arr.astype("<f4", copy=False).tobytes(),
        component=5126,
        count=len(positions_arr),
        kind="VEC3",
        target=34962,
        minimum=[float(value) for value in positions_arr.min(axis=0)],
        maximum=[float(value) for value in positions_arr.max(axis=0)],
    )
    normal_accessor = add_accessor(
        normals.astype("<f4", copy=False).tobytes(),
        component=5126,
        count=len(normals),
        kind="VEC3",
        target=34962,
    )
    uv_accessor = add_accessor(
        uv_arr.astype("<f4", copy=False).tobytes(),
        component=5126,
        count=len(uv_arr),
        kind="VEC2",
        target=34962,
    )
    joints_accessor = add_accessor(
        joints_arr.astype("<u2", copy=False).tobytes(),
        component=5123,
        count=len(joints_arr),
        kind="VEC4",
        target=34962,
    )
    weights_accessor = add_accessor(
        weights_arr.astype("<f4", copy=False).tobytes(),
        component=5126,
        count=len(weights_arr),
        kind="VEC4",
        target=34962,
    )
    index_accessor = add_accessor(
        indices_arr.astype("<u4", copy=False).tobytes(),
        component=5125,
        count=int(indices_arr.size),
        kind="SCALAR",
        target=34963,
    )
    texture_view = add_view(texture_png)
    images.append({"name": "BodyRigSourceHairReviewTexture", "bufferView": texture_view, "mimeType": "image/png"})
    textures.append({"sampler": 0, "source": len(images) - 1})
    hair_texture_index = len(textures) - 1
    materials.append({
        "name": "BodyRigSourceHairReviewMaterial",
        "doubleSided": True,
        "pbrMetallicRoughness": {
            "baseColorTexture": {"index": hair_texture_index},
            "metallicFactor": 0.0,
            "roughnessFactor": 0.72,
        },
    })
    hair_material_index = len(materials) - 1
    meshes.append({
        "name": "BodyRigSourceHairReviewMesh",
        "primitives": [{
            "attributes": {
                "POSITION": pos_accessor,
                "NORMAL": normal_accessor,
                "TEXCOORD_0": uv_accessor,
                "JOINTS_0": joints_accessor,
                "WEIGHTS_0": weights_accessor,
            },
            "indices": index_accessor,
            "material": hair_material_index,
            "mode": 4,
        }],
    })
    hair_mesh_index = len(meshes) - 1
    nodes.append({"name": "BodyRigSourceHairReview", "mesh": hair_mesh_index, "skin": 0})
    hair_node_index = len(nodes) - 1
    scenes[0]["nodes"].append(hair_node_index)
    bodyrig["hairReviewRuntime"] = dict(metadata)
    buffers[0]["byteLength"] = len(binary)
    return _write_glb(document, bytes(binary)), hair_mesh_index, len(positions_arr), int(indices_arr.size // 3)


def build(
    *,
    avatar_vrm: Path,
    binding_json: Path,
    candidate_workspace: Path,
    candidate_dir: Path,
    model_dir: str,
    output_vrm: Path,
    output_result: Path,
) -> dict[str, Any]:
    avatar_vrm = avatar_vrm.expanduser().resolve()
    binding_json = binding_json.expanduser().resolve()
    candidate_workspace = candidate_workspace.expanduser().resolve()
    candidate_dir = candidate_dir.expanduser().resolve()
    output_vrm = output_vrm.expanduser().resolve()
    output_result = output_result.expanduser().resolve()
    if output_vrm.exists() or output_result.exists():
        raise HairReviewRuntimeError("hair review bridge output is create-only")
    if not avatar_vrm.is_file() or not binding_json.is_file() or not candidate_workspace.is_dir() or not candidate_dir.is_dir():
        raise HairReviewRuntimeError("hair review bridge input boundary is incomplete")
    if not model_dir.startswith("/"):
        raise HairReviewRuntimeError("SMPL-X model directory must be an absolute Linux path")

    avatar_bytes = avatar_vrm.read_bytes()
    try:
        document, binary = _read_glb(avatar_bytes)
    except PbrMaterialError as exc:
        raise HairReviewRuntimeError(f"base avatar is invalid GLB: {exc}") from exc
    geometry = _geometry(document)
    avatar_sha = _sha256_bytes(avatar_bytes)
    binding = _binding(binding_json, avatar_sha=avatar_sha, geometry=geometry)
    donor_obj, _fit_params, hair_obj, hair_texture = _validate_exact_inputs(
        workspace=candidate_workspace,
        candidate_dir=candidate_dir,
        geometry=geometry,
        binding=binding,
    )
    if _sha256(donor_obj) != geometry["fittedDonorObjSha256"]:
        raise HairReviewRuntimeError("candidate donor changed after authority validation")

    rest_positions, texcoords, faces, joints4, weights4, final_joints, parents, metrics = _inverse_skin_hair(
        workspace=candidate_workspace,
        hair_obj=hair_obj,
        model_dir=model_dir,
        gender=str(geometry["bodyModelGender"]),
        replay=geometry["bodyprintGeometryAdjustment"],
    )
    _verify_avatar_skeleton(document, final_joints=final_joints, parents=parents)

    binding_sha = _sha256(binding_json)
    metadata = {
        "format": "bodyrig-source-hair-review-runtime-metadata",
        "version": 1,
        "baseAvatarVrmSha256": avatar_sha,
        "sourceHairBodyBindingSha256": binding_sha,
        "hairCandidateReceiptSha256": binding["hairCandidateReceiptSha256"],
        "hairObjSha256": binding["hairObjSha256"],
        "hairTextureSha256": binding["hairTextureSha256"],
        "targetModelFamily": geometry["bodyModelGender"],
        "skinIndex": 0,
        "bodyprintGeometryReplayApplied": bool(geometry["bodyprintGeometryAdjustment"]["applied"]),
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "productionActivation": False,
    }
    review_vrm, hair_mesh_index, vertex_count, face_count = _append_hair_mesh(
        document=document,
        binary_bytes=binary,
        rest_positions=rest_positions,
        texcoords=texcoords,
        faces=faces,
        joints4=joints4,
        weights4=weights4,
        texture_png=hair_texture.read_bytes(),
        metadata=metadata,
    )
    output_vrm.parent.mkdir(parents=True, exist_ok=True)
    output_vrm.write_bytes(review_vrm)
    result = {
        "format": FORMAT,
        "version": VERSION,
        "baseAvatarVrmSha256": avatar_sha,
        "sourceHairBodyBindingSha256": binding_sha,
        "reviewVrmSha256": _sha256_bytes(review_vrm),
        "targetModelFamily": geometry["bodyModelGender"],
        "skinIndex": 0,
        "hairMeshIndex": hair_mesh_index,
        "hairVertexCount": vertex_count,
        "hairFaceCount": face_count,
        "fitMax": round(float(metrics["fit_max"]), 9),
        "fitRms": round(float(metrics["fit_rms"]), 9),
        "nearestDonorDistanceP95": round(float(metrics["nearest_p95"]), 9),
        "nearestDonorDistanceMax": round(float(metrics["nearest_max"]), 9),
        "bodyprintGeometryReplayApplied": bool(geometry["bodyprintGeometryAdjustment"]["applied"]),
        "bodyprintMaxJointDelta": round(float(metrics["bodyprint_max_joint_delta"]), 9),
        "physicalSilhouetteReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "hairComponentAuthority": False,
        "productionActivation": False,
    }
    output_result.write_text(
        json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a comparison-only source-hair review VRM on the exact BodyRig skin.")
    parser.add_argument("--avatar-vrm", required=True)
    parser.add_argument("--binding-json", required=True)
    parser.add_argument("--candidate-workspace", required=True)
    parser.add_argument("--candidate-dir", required=True)
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--output-vrm", required=True)
    parser.add_argument("--output-result", required=True)
    args = parser.parse_args(argv)
    try:
        result = build(
            avatar_vrm=Path(args.avatar_vrm),
            binding_json=Path(args.binding_json),
            candidate_workspace=Path(args.candidate_workspace),
            candidate_dir=Path(args.candidate_dir),
            model_dir=str(args.smplx_model_dir),
            output_vrm=Path(args.output_vrm),
            output_result=Path(args.output_result),
        )
        print(json.dumps(result, separators=(",", ":"), allow_nan=False))
        return 0
    except Exception as exc:
        print(f"BodyRig source hair review runtime: FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
