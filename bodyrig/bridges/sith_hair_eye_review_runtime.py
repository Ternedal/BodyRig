#!/usr/bin/env python
"""Build one comparison VRM with source hair, explicit source-look eyes and cornea.

This is deliberately a visual runtime artifact, not component or production authority.
It reuses the exact source-hair runtime bridge, then overlays explicit left/right
SMPL-X eye submeshes using the source-derived canonical eye bake and a generic
transparent corneal shell. Eye skinning remains on the canonical SMPL-X skin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence

import sith_canonical_texture_bake as canonical
import sith_eye_component_extract as eye_geometry
import sith_hair_review_runtime as hair
import sith_smplx_vrm_fitter as base
from sith_pbr_material import PbrMaterialError, _read_glb, _write_glb

FORMAT = "bodyrig-source-hair-eye-review-bridge"
VERSION = 1
EYE_METADATA_FORMAT = "bodyrig-source-eye-review-runtime-metadata"
EYE_METADATA_VERSION = 1
SURFACE_SCALE = 1.0015
CORNEA_SCALE = 1.012


class HairEyeReviewRuntimeError(ValueError):
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
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HairEyeReviewRuntimeError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise HairEyeReviewRuntimeError(f"{label} must be an object")
    return value


def _lower_sha(value: Any, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise HairEyeReviewRuntimeError(f"{label} is invalid")
    return value


def _validate_eye_inputs(
    *,
    geometry: Mapping[str, Any],
    eye_geometry_dir: Path,
    eye_appearance_dir: Path,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    geometry_receipt_path = eye_geometry_dir / "eye-component-candidate.json"
    left_obj = eye_geometry_dir / "left_eye.obj"
    right_obj = eye_geometry_dir / "right_eye.obj"
    appearance_receipt_path = eye_appearance_dir / "eye-appearance-candidate.json"
    canonical_bake = eye_appearance_dir / "canonical_eye_source_bake.png"
    left_crop = eye_appearance_dir / "left_eye_appearance.png"
    right_crop = eye_appearance_dir / "right_eye_appearance.png"
    for path in (
        geometry_receipt_path,
        left_obj,
        right_obj,
        appearance_receipt_path,
        canonical_bake,
        left_crop,
        right_crop,
    ):
        if not path.is_file():
            raise HairEyeReviewRuntimeError(f"eye review artifact is missing: {path.name}")

    component = _load_json(geometry_receipt_path, label="eye component candidate")
    expected_component_fields = {
        "format", "version", "method", "targetModelFamily", "donorObjSha256",
        "leftEyeObjSha256", "rightEyeObjSha256", "leftEyeFaceCount", "rightEyeFaceCount",
        "leftEyeJointIndex", "rightEyeJointIndex", "explicitEyeGeometry", "geometryAuthority",
        "sourceDerivedIrisAppearance", "irisAppearanceStatus", "cornealMaterialStatus",
        "eyelashStatus", "bodyTopologyModified", "generativeIdentitySynthesis", "componentStatus",
        "comparisonOnly", "humanReviewRequired", "productionReady",
    }
    if set(component) != expected_component_fields:
        raise HairEyeReviewRuntimeError("eye component candidate fields do not match v1")
    if component.get("format") != "bodyrig-eye-component-candidate" or component.get("version") != 1:
        raise HairEyeReviewRuntimeError("eye component candidate format/version mismatch")
    if component.get("method") != "smplx-eye-joint-lbs-submesh-v1":
        raise HairEyeReviewRuntimeError("eye component extraction method mismatch")
    if component.get("targetModelFamily") != geometry.get("bodyModelGender"):
        raise HairEyeReviewRuntimeError("eye component target family differs from body geometry authority")
    if component.get("donorObjSha256") != geometry.get("fittedDonorObjSha256"):
        raise HairEyeReviewRuntimeError("eye component donor differs from body geometry authority")
    if component.get("leftEyeObjSha256") != _sha256(left_obj) or component.get("rightEyeObjSha256") != _sha256(right_obj):
        raise HairEyeReviewRuntimeError("eye component OBJ bytes changed after discovery")
    if (
        component.get("leftEyeJointIndex") != eye_geometry.LEFT_EYE_JOINT
        or component.get("rightEyeJointIndex") != eye_geometry.RIGHT_EYE_JOINT
        or component.get("explicitEyeGeometry") is not True
        or component.get("sourceDerivedIrisAppearance") is not False
        or component.get("irisAppearanceStatus") != "missing"
        or component.get("cornealMaterialStatus") != "missing"
        or component.get("bodyTopologyModified") is not False
        or component.get("generativeIdentitySynthesis") is not False
        or component.get("componentStatus") != "partial"
        or component.get("comparisonOnly") is not True
        or component.get("humanReviewRequired") is not True
        or component.get("productionReady") is not False
    ):
        raise HairEyeReviewRuntimeError("eye component candidate crossed the review-only boundary")

    appearance = _load_json(appearance_receipt_path, label="eye appearance candidate")
    required_appearance = {
        "format", "version", "method", "targetModelFamily", "donorObjSha256",
        "sourceReconstructionSha256", "sourceMeshSha256", "sourceTextureSha256",
        "canonicalBakeSha256", "leftEyeAppearancePngSha256", "rightEyeAppearancePngSha256",
        "leftEyeFaceCount", "rightEyeFaceCount", "leftMaskPixelCount", "rightMaskPixelCount",
        "bakeResolution", "sourceDerivedEyeSurfaceAppearance", "irisIdentityIsolated",
        "irisAppearanceStatus", "cornealMaterialStatus", "eyelashStatus", "bodyTopologyModified",
        "generativeIdentitySynthesis", "componentStatus", "comparisonOnly", "humanReviewRequired",
        "productionReady", "bakeSurfaceDistanceP95", "bakeSurfaceDistanceMax",
    }
    if set(appearance) != required_appearance:
        raise HairEyeReviewRuntimeError("eye appearance candidate fields do not match v1")
    if appearance.get("format") != "bodyrig-eye-appearance-candidate" or appearance.get("version") != 1:
        raise HairEyeReviewRuntimeError("eye appearance candidate format/version mismatch")
    if appearance.get("targetModelFamily") != geometry.get("bodyModelGender"):
        raise HairEyeReviewRuntimeError("eye appearance target family differs from body geometry authority")
    exact_pairs = {
        "donorObjSha256": "fittedDonorObjSha256",
        "sourceReconstructionSha256": "reconstructionSha256",
        "sourceMeshSha256": "sourceMeshSha256",
        "sourceTextureSha256": "sourceTextureSha256",
    }
    for appearance_field, geometry_field in exact_pairs.items():
        if appearance.get(appearance_field) != geometry.get(geometry_field):
            raise HairEyeReviewRuntimeError(f"eye appearance does not match body authority: {appearance_field}")
    if appearance.get("canonicalBakeSha256") != _sha256(canonical_bake):
        raise HairEyeReviewRuntimeError("canonical eye bake bytes changed after discovery")
    if appearance.get("leftEyeAppearancePngSha256") != _sha256(left_crop) or appearance.get("rightEyeAppearancePngSha256") != _sha256(right_crop):
        raise HairEyeReviewRuntimeError("eye appearance crop bytes changed after discovery")
    if appearance.get("leftEyeFaceCount") != component.get("leftEyeFaceCount") or appearance.get("rightEyeFaceCount") != component.get("rightEyeFaceCount"):
        raise HairEyeReviewRuntimeError("eye geometry/appearance face counts disagree")
    if (
        appearance.get("sourceDerivedEyeSurfaceAppearance") is not True
        or appearance.get("irisIdentityIsolated") is not False
        or appearance.get("irisAppearanceStatus") != "review-pending"
        or appearance.get("cornealMaterialStatus") != "missing"
        or appearance.get("bodyTopologyModified") is not False
        or appearance.get("generativeIdentitySynthesis") is not False
        or appearance.get("componentStatus") != "partial"
        or appearance.get("comparisonOnly") is not True
        or appearance.get("humanReviewRequired") is not True
        or appearance.get("productionReady") is not False
    ):
        raise HairEyeReviewRuntimeError("eye appearance candidate crossed the review-only boundary")
    bake_bytes = canonical_bake.read_bytes()
    if not bake_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise HairEyeReviewRuntimeError("canonical eye source bake is not PNG")
    return component, appearance, bake_bytes


def _eye_geometry_runtime(
    *,
    candidate_workspace: Path,
    model_dir: str,
    uv_obj: Path,
    geometry: Mapping[str, Any],
    component: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], Any, list[int]]:
    try:
        import numpy as np
        import torch
        from smplx import SMPLX
        from smplx.lbs import blend_shapes, vertices2joints
    except ImportError as exc:
        raise HairEyeReviewRuntimeError(f"eye runtime dependencies are unavailable: {exc}") from exc

    stage = candidate_workspace / "sith-input-v1"
    donor_path = stage / "smplx" / "000_smplx.obj"
    params_path = stage / "smplx" / "000_fit.json"
    if not donor_path.is_file() or not params_path.is_file():
        raise HairEyeReviewRuntimeError("candidate workspace lacks exact fitted SMPL-X inputs")
    if _sha256(donor_path) != geometry.get("fittedDonorObjSha256"):
        raise HairEyeReviewRuntimeError("candidate workspace donor differs from body geometry authority")
    params = base._fit_params(params_path)
    donor_positions = base._parse_positions(donor_path)
    gender = str(geometry.get("bodyModelGender"))
    try:
        model = SMPLX(
            model_path=model_dir,
            gender=gender,
            use_pca=False,
            flat_hand_mean=False,
            use_face_contour=True,
            num_betas=10,
            num_expression_coeffs=10,
        )
    except Exception as exc:
        raise HairEyeReviewRuntimeError(f"failed to load licensed SMPL-X {gender} model") from exc
    model.eval()
    if int(model.lbs_weights.shape[0]) != len(donor_positions):
        raise HairEyeReviewRuntimeError("eye runtime SMPL-X topology differs from candidate donor")

    faces_raw = getattr(model, "faces", None)
    if faces_raw is None:
        faces_raw = getattr(model, "faces_tensor", None)
        if faces_raw is None:
            raise HairEyeReviewRuntimeError("SMPL-X model exposes no face topology")
        faces = [[int(value) for value in face] for face in faces_raw.detach().cpu().tolist()]
    else:
        values = faces_raw.tolist() if hasattr(faces_raw, "tolist") else list(faces_raw)
        faces = [[int(value) for value in face] for face in values]

    left_faces = eye_geometry.select_eye_faces(
        lbs_weights=model.lbs_weights.detach().cpu().numpy().astype(np.float64).tolist(),
        faces=faces,
        joint_index=eye_geometry.LEFT_EYE_JOINT,
    )
    right_faces = eye_geometry.select_eye_faces(
        lbs_weights=model.lbs_weights.detach().cpu().numpy().astype(np.float64).tolist(),
        faces=faces,
        joint_index=eye_geometry.RIGHT_EYE_JOINT,
    )
    if len(left_faces) != int(component["leftEyeFaceCount"]) or len(right_faces) != int(component["rightEyeFaceCount"]):
        raise HairEyeReviewRuntimeError("runtime SMPL-X eye selection differs from discovery evidence")

    vertex_count, texcoords, canonical_faces, texture_faces = canonical.load_canonical_smplx_uv_template(uv_obj)
    if vertex_count != len(donor_positions) or canonical_faces != [tuple(face) for face in faces]:
        raise HairEyeReviewRuntimeError("canonical SMPL-X UV topology differs from eye runtime topology")

    device = model.v_template.device
    betas = torch.tensor(params["betas"], dtype=torch.float32, device=device).view(1, 10)
    expression = torch.tensor(params["expression"], dtype=torch.float32, device=device).view(1, 10)
    shape_components = torch.cat([betas, expression], dim=-1)
    shapedirs = torch.cat([model.shapedirs, model.expr_dirs], dim=-1)
    with torch.no_grad():
        v_shaped = model.v_template + blend_shapes(shape_components, shapedirs)
        rest_joints = vertices2joints(model.J_regressor, v_shaped)
    rest_all = v_shaped[0].detach().cpu().numpy().astype(np.float32, copy=True)
    rest_joints_np = rest_joints[0].detach().cpu().numpy().astype(np.float32, copy=True)
    lbs = model.lbs_weights.detach().cpu().numpy().astype(np.float32, copy=True)
    top_joint = np.argsort(lbs, axis=1)[:, -4:][:, ::-1].astype(np.int64, copy=False)
    top_weight = np.take_along_axis(lbs, top_joint, axis=1)
    totals = top_weight.sum(axis=1, keepdims=True)
    if bool(np.any(totals <= 1e-8)):
        raise HairEyeReviewRuntimeError("eye runtime skin weights contain empty influence sets")
    top_weight = top_weight / totals

    adjustment = hair._transient_adjustment(geometry.get("bodyprintGeometryAdjustment", {}))
    if adjustment is not None:
        try:
            rest_all, rest_joints_np, _metrics = hair.apply_shape_adjustment(
                np=np,
                rest_positions=rest_all,
                rest_joints=rest_joints_np,
                joints4=top_joint,
                weights4=top_weight,
                joint_names=base.SMPLX_JOINT_NAMES,
                adjustment=adjustment,
            )
        except Exception as exc:
            raise HairEyeReviewRuntimeError(f"eye BodyPrint geometry replay failed: {exc}") from exc

    parents = [int(value) for value in model.parents.detach().cpu().tolist()]
    side_data: dict[str, Any] = {}
    for side, selected, joint_index in (
        ("left", left_faces, eye_geometry.LEFT_EYE_JOINT),
        ("right", right_faces, eye_geometry.RIGHT_EYE_JOINT),
    ):
        side_data[side] = {
            "selected_faces": selected,
            "joint_index": joint_index,
            "center": rest_joints_np[joint_index],
            "rest_positions": rest_all,
            "texcoords": texcoords,
            "texture_faces": texture_faces,
            "geometry_faces": faces,
            "joints4": top_joint,
            "weights4": top_weight,
        }
    return side_data["left"], side_data["right"], rest_joints_np, parents


def _primitive_arrays(np: Any, *, side: Mapping[str, Any], scale: float) -> tuple[Any, Any, Any, Any, Any, Any]:
    selected_faces = side["selected_faces"]
    center = np.asarray(side["center"], dtype=np.float32)
    rest = side["rest_positions"]
    texcoords = side["texcoords"]
    texture_faces = side["texture_faces"]
    geometry_faces = side["geometry_faces"]
    joints4 = side["joints4"]
    weights4 = side["weights4"]

    vertex_map: dict[tuple[int, int], int] = {}
    positions: list[Any] = []
    uv: list[tuple[float, float]] = []
    joints: list[Any] = []
    weights: list[Any] = []
    indices: list[int] = []
    for face_index in selected_faces:
        geometry_face = geometry_faces[face_index]
        uv_face = texture_faces[face_index]
        if len(geometry_face) != 3 or len(uv_face) != 3:
            raise HairEyeReviewRuntimeError("eye runtime face topology is not triangular")
        for vertex_index, uv_index in zip(geometry_face, uv_face):
            key = (int(vertex_index), int(uv_index))
            mapped = vertex_map.get(key)
            if mapped is None:
                mapped = len(positions)
                vertex_map[key] = mapped
                raw = np.asarray(rest[vertex_index], dtype=np.float32)
                positions.append(center + (raw - center) * float(scale))
                u, v = texcoords[uv_index]
                uv.append((float(u), float(1.0 - v)))
                joints.append(joints4[vertex_index])
                weights.append(weights4[vertex_index])
            indices.append(mapped)
    pos = np.asarray(positions, dtype=np.float32)
    uv_arr = np.asarray(uv, dtype=np.float32)
    joints_arr = np.asarray(joints, dtype=np.uint16)
    weights_arr = np.asarray(weights, dtype=np.float32)
    idx = np.asarray(indices, dtype=np.uint32)
    if len(pos) < 3 or idx.size < 3:
        raise HairEyeReviewRuntimeError("eye runtime mesh contains too little geometry")
    normals = np.zeros_like(pos)
    for a, b, c in idx.reshape(-1, 3):
        normal = np.cross(pos[b] - pos[a], pos[c] - pos[a])
        normals[a] += normal
        normals[b] += normal
        normals[c] += normal
    lengths = np.linalg.norm(normals, axis=1)
    valid = lengths > 1e-12
    normals[valid] /= lengths[valid, None]
    normals[~valid] = np.asarray([0.0, 0.0, 1.0], dtype=np.float32)
    return pos, normals, uv_arr, joints_arr, weights_arr, idx


def _append_eyes(
    *,
    document: dict[str, Any],
    binary_bytes: bytes,
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    source_bake_png: bytes,
    metadata: Mapping[str, Any],
) -> tuple[bytes, int, dict[str, int]]:
    try:
        import numpy as np
    except ImportError as exc:
        raise HairEyeReviewRuntimeError(f"numpy is required for eye GLB serialization: {exc}") from exc

    keys = ("bufferViews", "accessors", "images", "textures", "materials", "meshes", "nodes", "scenes", "samplers", "buffers")
    arrays = {key: document.get(key) for key in keys}
    if any(not isinstance(value, list) for value in arrays.values()):
        raise HairEyeReviewRuntimeError("hair review VRM glTF arrays are incomplete")
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
    if not samplers or len(buffers) != 1 or not isinstance(buffers[0], dict):
        raise HairEyeReviewRuntimeError("hair review VRM sampler/buffer contract is unsupported")
    if not scenes or not isinstance(scenes[0], dict) or not isinstance(scenes[0].get("nodes"), list):
        raise HairEyeReviewRuntimeError("hair review VRM scene contract is unsupported")
    extras = document.get("extras")
    bodyrig = extras.get("bodyrig") if isinstance(extras, dict) else None
    if not isinstance(bodyrig, dict) or "hairReviewRuntime" not in bodyrig:
        raise HairEyeReviewRuntimeError("hair review authority is missing before eye integration")
    if "eyeReviewRuntime" in bodyrig:
        raise HairEyeReviewRuntimeError("review VRM already contains eye runtime metadata")

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

    def add_accessor(array: Any, *, component: int, kind: str, target: int | None = None, bounds: bool = False) -> int:
        if component == 5126:
            raw = array.astype("<f4", copy=False).tobytes()
        elif component == 5123:
            raw = array.astype("<u2", copy=False).tobytes()
        elif component == 5125:
            raw = array.astype("<u4", copy=False).tobytes()
        else:
            raise HairEyeReviewRuntimeError("unsupported eye accessor component type")
        view = add_view(raw, target=target)
        accessor: dict[str, Any] = {"bufferView": view, "componentType": component, "count": len(array), "type": kind}
        if bounds:
            accessor["min"] = [float(value) for value in array.min(axis=0)]
            accessor["max"] = [float(value) for value in array.max(axis=0)]
        accessors.append(accessor)
        return len(accessors) - 1

    texture_view = add_view(source_bake_png)
    images.append({"name": "BodyRigSourceEyeBake", "bufferView": texture_view, "mimeType": "image/png"})
    textures.append({"sampler": 0, "source": len(images) - 1})
    eye_texture = len(textures) - 1
    materials.append({
        "name": "BodyRigSourceEyeSurface",
        "doubleSided": False,
        "pbrMetallicRoughness": {
            "baseColorTexture": {"index": eye_texture},
            "metallicFactor": 0.0,
            "roughnessFactor": 0.36,
        },
    })
    surface_material = len(materials) - 1
    materials.append({
        "name": "BodyRigCorneaReview",
        "doubleSided": False,
        "alphaMode": "BLEND",
        "pbrMetallicRoughness": {
            "baseColorFactor": [1.0, 1.0, 1.0, 0.11],
            "metallicFactor": 0.0,
            "roughnessFactor": 0.04,
        },
    })
    cornea_material = len(materials) - 1

    primitives: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    for side_name, side in (("left", left), ("right", right)):
        surface = _primitive_arrays(np, side=side, scale=SURFACE_SCALE)
        cornea = _primitive_arrays(np, side=side, scale=CORNEA_SCALE)
        for label, arrays_for_primitive, material in (
            ("surface", surface, surface_material),
            ("cornea", cornea, cornea_material),
        ):
            pos, normals, uv, joints, weights, indices = arrays_for_primitive
            pos_accessor = add_accessor(pos, component=5126, kind="VEC3", target=34962, bounds=True)
            normal_accessor = add_accessor(normals, component=5126, kind="VEC3", target=34962)
            uv_accessor = add_accessor(uv, component=5126, kind="VEC2", target=34962)
            joints_accessor = add_accessor(joints, component=5123, kind="VEC4", target=34962)
            weights_accessor = add_accessor(weights, component=5126, kind="VEC4", target=34962)
            index_accessor = add_accessor(indices, component=5125, kind="SCALAR", target=34963)
            primitives.append({
                "attributes": {
                    "POSITION": pos_accessor,
                    "NORMAL": normal_accessor,
                    "TEXCOORD_0": uv_accessor,
                    "JOINTS_0": joints_accessor,
                    "WEIGHTS_0": weights_accessor,
                },
                "indices": index_accessor,
                "material": material,
                "mode": 4,
            })
            counts[f"{side_name}_{label}_vertices"] = int(len(pos))
            counts[f"{side_name}_{label}_faces"] = int(indices.size // 3)

    meshes.append({"name": "BodyRigSourceEyeReviewMesh", "primitives": primitives})
    mesh_index = len(meshes) - 1
    nodes.append({"name": "BodyRigSourceEyeReview", "mesh": mesh_index, "skin": 0})
    node_index = len(nodes) - 1
    scenes[0]["nodes"].append(node_index)
    bodyrig["eyeReviewRuntime"] = dict(metadata)
    buffers[0]["byteLength"] = len(binary)
    return _write_glb(document, bytes(binary)), mesh_index, counts


def build(
    *,
    avatar_vrm: Path,
    hair_binding_json: Path,
    candidate_workspace: Path,
    hair_candidate_dir: Path,
    eye_geometry_dir: Path,
    eye_appearance_dir: Path,
    model_dir: str,
    smplx_uv_obj: Path,
    output_vrm: Path,
    output_result: Path,
) -> dict[str, Any]:
    output_vrm = output_vrm.expanduser().resolve()
    output_result = output_result.expanduser().resolve()
    if output_vrm.exists() or output_result.exists():
        raise HairEyeReviewRuntimeError("hair+eye review output is create-only")
    output_vrm.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="bodyrig-hair-eye-") as temp_root:
        temp = Path(temp_root)
        hair_vrm = temp / "hair-review.vrm"
        hair_result_path = temp / "hair-review.json"
        hair_result = hair.build(
            avatar_vrm=avatar_vrm,
            binding_json=hair_binding_json,
            candidate_workspace=candidate_workspace,
            candidate_dir=hair_candidate_dir,
            model_dir=model_dir,
            output_vrm=hair_vrm,
            output_result=hair_result_path,
        )
        hair_bytes = hair_vrm.read_bytes()
        try:
            document, binary = _read_glb(hair_bytes)
        except PbrMaterialError as exc:
            raise HairEyeReviewRuntimeError(f"hair review output is invalid GLB: {exc}") from exc
        geometry = hair._geometry(document)
        component, appearance, bake_bytes = _validate_eye_inputs(
            geometry=geometry,
            eye_geometry_dir=eye_geometry_dir.expanduser().resolve(),
            eye_appearance_dir=eye_appearance_dir.expanduser().resolve(),
        )
        left, right, final_joints, parents = _eye_geometry_runtime(
            candidate_workspace=candidate_workspace.expanduser().resolve(),
            model_dir=model_dir,
            uv_obj=smplx_uv_obj.expanduser().resolve(),
            geometry=geometry,
            component=component,
        )
        hair._verify_avatar_skeleton(document, final_joints=final_joints, parents=parents)
        eye_metadata = {
            "format": EYE_METADATA_FORMAT,
            "version": EYE_METADATA_VERSION,
            "eyeComponentReceiptSha256": _sha256(eye_geometry_dir / "eye-component-candidate.json"),
            "eyeAppearanceReceiptSha256": _sha256(eye_appearance_dir / "eye-appearance-candidate.json"),
            "canonicalEyeBakeSha256": appearance["canonicalBakeSha256"],
            "targetModelFamily": geometry["bodyModelGender"],
            "leftEyeJointIndex": eye_geometry.LEFT_EYE_JOINT,
            "rightEyeJointIndex": eye_geometry.RIGHT_EYE_JOINT,
            "sourceEyeSurfaceApplied": True,
            "irisIdentityIsolated": False,
            "irisAppearanceStatus": "review-pending",
            "cornealMaterialStatus": "runtime-applied",
            "eyelashStatus": "missing",
            "skinIndex": 0,
            "physicalFaceCloseupReviewRequired": True,
            "comparisonOnly": True,
            "humanReviewRequired": True,
            "eyeComponentAuthority": False,
            "productionActivation": False,
        }
        combined, eye_mesh_index, counts = _append_eyes(
            document=document,
            binary_bytes=binary,
            left=left,
            right=right,
            source_bake_png=bake_bytes,
            metadata=eye_metadata,
        )

    output_vrm.write_bytes(combined)
    result = {
        "format": FORMAT,
        "version": VERSION,
        "baseAvatarVrmSha256": hair_result["baseAvatarVrmSha256"],
        "sourceHairBodyBindingSha256": hair_result["sourceHairBodyBindingSha256"],
        "hairReviewBridgeSha256": _sha256_bytes(json.dumps(hair_result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")),
        "hairMeshIndex": hair_result["hairMeshIndex"],
        "eyeMeshIndex": eye_mesh_index,
        "reviewVrmSha256": _sha256_bytes(combined),
        "targetModelFamily": geometry["bodyModelGender"],
        "leftEyeFaceCount": int(component["leftEyeFaceCount"]),
        "rightEyeFaceCount": int(component["rightEyeFaceCount"]),
        "leftEyeRuntimeVertices": counts["left_surface_vertices"],
        "rightEyeRuntimeVertices": counts["right_surface_vertices"],
        "sourceHairRuntimeApplied": True,
        "sourceEyeSurfaceApplied": True,
        "irisIdentityIsolated": False,
        "irisAppearanceStatus": "review-pending",
        "cornealMaterialStatus": "runtime-applied",
        "eyelashStatus": "missing",
        "physicalSilhouetteReviewRequired": True,
        "physicalFaceCloseupReviewRequired": True,
        "comparisonOnly": True,
        "humanReviewRequired": True,
        "hairComponentAuthority": False,
        "eyeComponentAuthority": False,
        "productionActivation": False,
    }
    output_result.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build one review VRM with source hair and explicit source-look eyes.")
    parser.add_argument("--avatar-vrm", required=True)
    parser.add_argument("--hair-binding-json", required=True)
    parser.add_argument("--candidate-workspace", required=True)
    parser.add_argument("--hair-candidate-dir", required=True)
    parser.add_argument("--eye-geometry-dir", required=True)
    parser.add_argument("--eye-appearance-dir", required=True)
    parser.add_argument("--smplx-model-dir", required=True)
    parser.add_argument("--smplx-uv-obj", required=True)
    parser.add_argument("--output-vrm", required=True)
    parser.add_argument("--output-result", required=True)
    args = parser.parse_args(argv)
    try:
        result = build(
            avatar_vrm=Path(args.avatar_vrm),
            hair_binding_json=Path(args.hair_binding_json),
            candidate_workspace=Path(args.candidate_workspace),
            hair_candidate_dir=Path(args.hair_candidate_dir),
            eye_geometry_dir=Path(args.eye_geometry_dir),
            eye_appearance_dir=Path(args.eye_appearance_dir),
            model_dir=str(args.smplx_model_dir),
            smplx_uv_obj=Path(args.smplx_uv_obj),
            output_vrm=Path(args.output_vrm),
            output_result=Path(args.output_result),
        )
        print(json.dumps(result, separators=(",", ":"), allow_nan=False))
        return 0
    except Exception as exc:
        print(f"BodyRig hair+eye review runtime: FAIL: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
